#!/usr/bin/env python3
"""Upload and deploy the FinReflectKG time-travel UI to the Arango Platform (BYOC).

Companion to ``deploy/package.sh``, which builds the bundle this uploads.
Ported from gdelt-market-impact's ``scripts/byoc_deploy.py``, which took it from
project-sentinel and arango-ontoextract — the platform-shaped half is identical for
every project. What differs here: the defaults, the pre-flight checks and the verifier.

Usage
-----
    python3 scripts/byoc_deploy.py list
    python3 scripts/byoc_deploy.py update                 # pre-flight, upload, swap, verify
    python3 scripts/byoc_deploy.py verify [--expect-version 0.1.0]
    python3 scripts/byoc_deploy.py rollback --to 1.0.0-1
    python3 scripts/byoc_deploy.py delete
    python3 scripts/byoc_deploy.py status --service-id arango-user-defined-xxxxx

Platform contract (docs/platform-deployment.md): flat tarball with a Python
``entrypoint`` at its root; the service listens on port 8000 and is mounted at
``/_service/uds/_db/<db>/<instance>/`` (trailing slash required); the platform
injects no environment, so credentials travel baked in the bundle's ``.env``.
There is no in-place update: ``update`` deletes and recreates, and the service
is gone for about a minute. Package versions are unique per name.

Configuration comes from the repo-root ``.env`` (``ARANGO_ENDPOINT``,
``ARANGO_USER``, ``ARANGO_PASSWORD``, ``ARANGO_DATABASE``); nothing here
writes a token to disk.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARBALL_DIR = REPO_ROOT / "target"
DEFAULT_APP_NAME = "finreflectkg-timetravel"
DEFAULT_INSTANCE = "finreflect"
# prod.demo offers node22base, py12base, py12cugraph, py12torch, test — confirmed
# by reading a live service's serviceMeta.udsMeta.baseImage. There is no py13base
# here, which is why the bundle installs from requirements.txt at boot rather than
# relying on a 3.13 image.
DEFAULT_BASE_IMAGE = "py12base"
DEFAULT_DISPLAY_NAME = "FinReflectKG Time Travel"
DEFAULT_DESCRIPTION = (
    "Point-in-time exploration of a decade of S&P 500 10-K filings as a bitemporal "
    "knowledge graph — scrub any company's neighbourhood through 2014-2024, rank it "
    "by corpus-wide PageRank, and see what appeared or disappeared between years."
)

ACP = "/_platform/acp/v1"
FILEMANAGER = "/_platform/filemanager/global/byoc/"
READY = {"DEPLOYED"}
FAILED = {"FAILED", "ERROR", "TERMINATED"}
SECRET_KEY_PATTERN = re.compile(r"^[A-Z0-9_]*_API_KEY\s*=\s*\S", re.M)


class DeployError(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    """Parse a dotenv file; surrounding quotes are stripped (a quoted password
    otherwise surfaces as an unexplained 401)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def tar_member_name(name: str) -> str:
    """Member name without a leading ``./`` (never ``lstrip('./')`` — it eats ``.env``)."""
    return name[2:] if name.startswith("./") else name


def mount_path(instance: str, db_name: str | None) -> str:
    """Public prefix the platform serves this instance under. Must equal the
    SERVICE_URL_PATH_PREFIX baked into the bundle's .env."""
    scope = f"_db/{db_name}" if db_name else "_global"
    return f"/_service/uds/{scope}/{instance}"


def newest_tarball() -> Path:
    """The most recently built bundle in ``target/``."""
    found = sorted(DEFAULT_TARBALL_DIR.glob("finreflectkg-timetravel-*.tar.gz"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not found:
        raise DeployError("no bundle in target/ — run ./deploy/package.sh <version> --with-env")
    return found[0]


def read_app_version(tarball: Path | None = None) -> str:
    """Release version, taken from the bundle's filename — the bundle is the
    artifact being deployed, so its name is the authority."""
    name = (tarball or newest_tarball()).name
    match = re.match(r"finreflectkg-timetravel-(.+)\.tar\.gz$", name)
    if not match:
        raise DeployError(f"cannot read a version from {name!r}")
    return match.group(1)


def _service_id_of(result: dict) -> tuple[str | None, str | None]:
    """(serviceId, status) from a deploy/status response; the create response
    nests them under ``serviceInfo``."""
    info = result.get("serviceInfo") if isinstance(result, dict) else None
    if not isinstance(info, dict):
        info = result if isinstance(result, dict) else {}
    return info.get("serviceId") or info.get("service_id"), info.get("status")


class Platform:
    """Thin client over the Container Manager endpoints used by a BYOC release."""

    def __init__(self, base: str, user: str, password: str, *, timeout: float = 60.0):
        self.base = base.rstrip("/")
        self.user = user
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self._jwt: str | None = None

    def authenticate(self) -> None:
        response = self.session.post(
            f"{self.base}/_open/auth",
            json={"username": self.user, "password": self.password},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise DeployError(f"auth failed: HTTP {response.status_code}")
        token = response.json().get("jwt")
        if not token:
            raise DeployError("auth response carried no 'jwt' field")
        self._jwt = token

    def _headers(self) -> dict[str, str]:
        if self._jwt is None:
            self.authenticate()
        return {"Authorization": f"Bearer {self._jwt}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        url = f"{self.base}{path}"
        response = self.session.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401:  # one transparent re-auth (slow uploads)
            self.authenticate()
            response = self.session.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            raise DeployError(f"{method} {path} -> HTTP {response.status_code}: {response.text[:400]}")
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text[:400]}

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        return self.session.get(url, headers=self._headers(), **kwargs)

    def list_packages(self) -> list[dict]:
        return self._request("GET", FILEMANAGER).get("services", [])

    def list_services(self) -> list[dict]:
        return self._request("POST", f"{ACP}/list_services", json={}).get("services", [])

    def upload(self, tarball: Path, name: str, version: str) -> dict:
        with tarball.open("rb") as handle:
            return self._request(
                "POST", FILEMANAGER,
                data={"name": name, "version": version, "language": "python", "type": "Service"},
                files={"file": (tarball.name, handle, "application/gzip")},
                timeout=600,
            )

    def deploy(self, name: str, version: str, instance: str, db_name: str | None,
               base_image: str, *, has_ui: bool = True, display_name: str | None = None,
               description: str | None = None) -> dict:
        # Every value must be a string: the platform decodes `env` as a string map.
        env: dict[str, str] = {"service_type": "base_type", "base_image": base_image,
                               "app_instance_name": instance}
        if db_name:
            env["db_name"] = db_name
        if has_ui:
            env["has_ui"] = "true"
        if display_name:
            env["display_name"] = display_name
        if description:
            env["description"] = description
        return self._request("POST", f"{ACP}/uds",
                             json={"app_name": name, "app_version": version, "env": env},
                             timeout=180)

    def service_status(self, service_id: str) -> dict:
        return self._request("GET", f"{ACP}/service/{service_id}")

    def delete_service(self, service_id: str) -> None:
        self._request("DELETE", f"{ACP}/service/{service_id}", timeout=120)

    def find_instances(self, instance: str) -> list[dict]:
        found = []
        for service in self.list_services():
            uds = ((service.get("serviceMeta") or {}).get("udsMeta")) or {}
            if uds.get("appInstanceName") == instance:
                found.append({"serviceId": service.get("serviceId"), "version": uds.get("version"),
                              "status": service.get("status"), "dbName": service.get("dbName")})
        return found

    def resolve_instance(self, instance: str) -> dict | None:
        matches = self.find_instances(instance)
        if len(matches) > 1:
            raise DeployError(f"{len(matches)} services run as instance {instance!r}: "
                              f"{[m['serviceId'] for m in matches]}. Delete the extras by id first.")
        return matches[0] if matches else None

    def wait_until_ready(self, service_id: str, *, timeout_s: float = 600.0,
                         interval_s: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout_s
        last: dict = {}
        while time.monotonic() < deadline:
            last = self.service_status(service_id)
            info = last.get("serviceInfo") if isinstance(last, dict) else {}
            info = info if isinstance(info, dict) else {}
            state = str(info.get("status") or last.get("status") or "").upper()
            if state in READY:
                return last
            if state in FAILED:
                raise DeployError(f"service {service_id} reached {state}: {last}")
            print(f"    status={state or '(unknown)'} — waiting {interval_s:.0f}s", flush=True)
            time.sleep(interval_s)
        raise DeployError(f"timed out after {timeout_s:.0f}s; last status: {last}")


def next_build_version(platform: Platform, name: str, release: str) -> str:
    """``<release>-<n>``: first suffix not already uploaded under ``name``."""
    taken = {p["version"] for p in platform.list_packages() if p.get("name") == name}
    for build in range(1, 1000):
        candidate = f"{release}-{build}"
        if candidate not in taken:
            return candidate
    raise DeployError(f"no free build suffix for {release}")


def preflight(tarball: Path, instance: str, db_name: str | None) -> None:
    """Refuse to upload an artifact that cannot work."""
    if not tarball.exists():
        raise DeployError(f"no tarball at {tarball} — run deploy/package.sh first")
    problems: list[str] = []
    with tarfile.open(tarball, "r:gz") as archive:
        names = {tar_member_name(n): n for n in archive.getnames()}

        def read(member: str) -> str:
            raw = names.get(member)
            if not raw:
                return ""
            handle = archive.extractfile(raw)
            return handle.read().decode("utf-8", "replace") if handle else ""

        for required in ("entrypoint", "requirements.txt", "demo/api.py",
                         "demo/prefix.py", "scripts/arango.py",
                         "demo/static/index.html", "demo/static/app.js",
                         "demo/static/style.css",
                         "demo/static/vendor/cytoscape.min.js"):
            if required not in names:
                problems.append(f"{required} missing from the archive root layout")
        entry = read("entrypoint")
        if entry and not entry.splitlines()[0].startswith("entrypoint"):
            problems.append("entrypoint line 1 must start with the token `entrypoint`")

        env_text = read(".env")
        if not env_text:
            problems.append(".env is not baked — the platform injects nothing, so the "
                            "service would have no credentials")
        else:
            env = {k.strip(): v.strip() for k, v in
                   (l.split("=", 1) for l in env_text.splitlines() if "=" in l and not l.startswith("#"))}
            for key in ("ARANGO_ENDPOINT", "ARANGO_USER", "ARANGO_PASSWORD"):
                if not env.get(key):
                    problems.append(f"{key} missing from the baked .env")
            if re.search(r"localhost|127\.0\.0\.1", env.get("ARANGO_ENDPOINT", "")):
                problems.append("ARANGO_ENDPOINT points at loopback — unreachable from the platform")
            if SECRET_KEY_PATTERN.search(env_text):
                problems.append("an *_API_KEY is baked into .env — rebuild with package.sh (sanitized)")
            expected = mount_path(instance, db_name)
            if env.get("SERVICE_URL_PATH_PREFIX", "").rstrip("/") != expected:
                problems.append(f"SERVICE_URL_PATH_PREFIX={env.get('SERVICE_URL_PATH_PREFIX')!r} "
                                f"but the deploy will mount at {expected!r} — rebuild with "
                                f"--instance/--db matching")
        index = read("demo/static/index.html")
        if index and re.search(r'(?:href|src)="/(?:static|api)', index):
            problems.append("index.html uses root-absolute asset URLs — they break under the mount path")
    if problems:
        raise DeployError("pre-flight failed:\n  - " + "\n  - ".join(problems))
    print("    pre-flight OK (layout, entrypoint, baked .env, mount prefix, relative assets)")


def resolve_config(args: argparse.Namespace) -> tuple[Platform, str, str | None]:
    env = load_env(REPO_ROOT / ".env")
    endpoint = args.endpoint or env.get("ARANGO_ENDPOINT")
    user = env.get("ARANGO_USER") or env.get("ARANGO_USERNAME")
    password = env.get("ARANGO_PASSWORD")
    if not endpoint or not user or not password:
        raise DeployError("need ARANGO_ENDPOINT, ARANGO_USER and ARANGO_PASSWORD in .env")
    # demo/api.py hardcodes the database it serves; the repo .env's ARANGO_DATABASE
    # is FinReflectKG, which does NOT exist on prod.demo. Mounting under a
    # non-existent database would put the service at an unreachable path.
    default_db = "FinReflectKgTemporal"
    db_name = default_db if args.db is None else (args.db or None)
    return Platform(endpoint, user, password), endpoint, db_name


def cmd_list(args: argparse.Namespace) -> int:
    platform, endpoint, _ = resolve_config(args)
    print(f"platform: {endpoint}\n\nuploaded packages (most recent first):")
    for package in platform.list_packages()[:15]:
        print(f"  {package['name']:<34} v{package['version']:<12} {package.get('file_name', '')}")
    print("\ndeployed user-defined services:")
    for service in platform.list_services():
        meta = service.get("serviceMeta") or {}
        if str(meta.get("serviceType", "")).startswith("arango-user-defined"):
            uds = meta.get("udsMeta") or {}
            print(f"  {service.get('serviceId'):<36} db={service.get('dbName') or '(global)':<18} "
                  f"instance={uds.get('appInstanceName')} v{uds.get('version')} {service.get('status')}")
    return 0


def deep_verify(platform: Platform, url: str, expect_version: str | None) -> bool:
    """Prove the *right code* is live and talking to the right data.

    Three things, because each has failed on its own: the API answers at all, the
    graph actually returns data (a service pointed at an empty or wrong database
    serves a perfectly healthy blank app), and every asset the page references loads
    (a mount-prefix mismatch shows a blank page behind a green light).

    This service has no /healthz, so `expect_version` cannot be checked against the
    running code; it is accepted and ignored rather than silently asserting a lie.
    """
    ok = True
    if expect_version:
        print(f"    note: no /healthz route — cannot confirm live version "
              f"{expect_version} from the service itself")
    try:
        years = platform.get(url + "api/years", timeout=90).json()
        tickers = platform.get(url + "api/tickers", timeout=120).json()
        print(f"    /api/years       {years}")
        print(f"    /api/tickers     {len(tickers)} companies")
        if not years.get("anchors"):
            print("    FAIL: no PageRank anchor years — wrong database?", file=sys.stderr)
            ok = False
        if len(tickers) < 700:
            print(f"    FAIL: only {len(tickers)} companies; the corpus has 743 — "
                  "wrong or partially loaded database", file=sys.stderr)
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"    FAIL: years/tickers unreadable: {exc}", file=sys.stderr)
        return False
    try:
        # A real graph query, not just a metadata endpoint: this is the one that
        # touches relations/Node and would expose a half-migrated database.
        graph = platform.get(url + "api/asof?ticker=aapl&year=2020&depth=1"
                                   "&clean=true&axis=valid", timeout=180).json()
        n, e = len(graph.get("nodes", [])), len(graph.get("edges", []))
        print(f"    /api/asof aapl   {n} nodes / {e} edges")
        if not n or not e:
            print("    FAIL: empty graph for a known-good company/year", file=sys.stderr)
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"    FAIL: graph query failed: {exc}", file=sys.stderr)
        ok = False
    try:
        html = platform.get(url).text
        # Relative, i.e. NOT starting with "/", "http" or "//". Root-absolute
        # assets are the prefix bug this check exists to catch.
        assets = list(dict.fromkeys(
            re.findall(r'(?:src|href)="(?!https?:|//|/)([^"]+)"', html)))
        broken = []
        for asset in assets:
            response = platform.get(url + asset.lstrip("./"))
            if response.status_code != 200:
                broken.append((response.status_code, asset))
        print(f"    assets           {len(assets) - len(broken)}/{len(assets)} served")
        for code, asset in broken:
            print(f"    FAIL: {code} {asset}", file=sys.stderr)
            ok = False
        if not assets:
            print("    FAIL: index references no relative assets — wrong page served?",
                  file=sys.stderr)
            ok = False
    except Exception as exc:  # noqa: BLE001
        print(f"    FAIL: could not check assets: {exc}", file=sys.stderr)
        ok = False
    print("    => VERIFIED" if ok else "    => VERIFICATION FAILED")
    return ok


def cmd_verify(args: argparse.Namespace) -> int:
    """Poll the public URL until the pod serves (404 = route not registered yet;
    401/503 = pod not ready — 503 is also what a freshly deleted service returns)."""
    platform, endpoint, db_name = resolve_config(args)
    platform.authenticate()
    url = f"{endpoint}{mount_path(args.instance, db_name)}/"
    print(f"==> polling {url}")
    deadline = time.monotonic() + args.wait_timeout
    while time.monotonic() < deadline:
        try:
            response = platform.get(url, allow_redirects=False)
            code = response.status_code
            if code == 200:
                print(f"    HTTP 200 — serving ({response.headers.get('content-type', '?')})")
                return 0 if deep_verify(platform, url, args.expect_version) else 1
            # Observed 2026-09-25 on the pilot cluster: the gateway answers 401 (to an
            # authenticated caller) until the pod is ready, then flips to 200 — so
            # 401 is a cold-start signal here, not an auth failure.
            hint = {404: "route not registered", 401: "gateway/pod not ready yet",
                    503: "pod not ready"}.get(code, "not serving yet")
            print(f"    HTTP {code} ({hint}) — retrying in {args.poll_interval:.0f}s", flush=True)
        except requests.RequestException as exc:
            print(f"    {type(exc).__name__} — retrying in {args.poll_interval:.0f}s", flush=True)
        time.sleep(args.poll_interval)
    print(f"error: {url} never returned 200 within {args.wait_timeout:.0f}s", file=sys.stderr)
    return 1


def _swap(platform: Platform, args: argparse.Namespace, db_name: str | None, version: str) -> int:
    """Delete-then-create — what an update *is* on this platform (a second
    install cannot take over the first one's Kubernetes objects)."""
    existing = platform.resolve_instance(args.instance)
    if existing:
        print(f"==> replacing {existing['serviceId']} (version {existing['version']} -> {version})")
        platform.delete_service(existing["serviceId"])
        print("    old service deleted — the URL is down from here")
    else:
        print(f"==> no existing instance {args.instance!r}; creating fresh")
    print(f"    will mount at: {mount_path(args.instance, db_name)}/   base image: {args.base_image}")
    result = platform.deploy(args.name, version, args.instance, db_name, args.base_image,
                             has_ui=not args.no_ui, display_name=args.display_name,
                             description=args.description)
    service_id, state = _service_id_of(result)
    print(f"    created {service_id} status={state}")
    if service_id:
        print("==> waiting for DEPLOYED...")
        platform.wait_until_ready(service_id, timeout_s=args.wait_timeout)
        print("    DEPLOYED (the pod may still be installing dependencies)")
    args.expect_version = getattr(args, "expect_version", None)
    args.poll_interval = getattr(args, "poll_interval", 15.0)
    return cmd_verify(args)


def cmd_update(args: argparse.Namespace) -> int:
    """Pre-flight, upload, swap, verify. Upload precedes delete so a rejected
    artifact fails while the old service still serves."""
    platform, _endpoint, db_name = resolve_config(args)
    tarball = Path(args.tarball) if args.tarball else newest_tarball()
    release = read_app_version()
    print(f"==> release {release} (from the bundle filename)")
    preflight(tarball, args.instance, db_name)
    version = args.version or next_build_version(platform, args.name, release)
    print(f"==> uploading {tarball.name} ({tarball.stat().st_size / 1_048_576:.1f} MB) as {args.name} v{version}")
    platform.upload(tarball, args.name, version)
    print("    uploaded")
    args.expect_version = release
    return _swap(platform, args, db_name, version)


def cmd_rollback(args: argparse.Namespace) -> int:
    platform, _endpoint, db_name = resolve_config(args)
    available = sorted({p["version"] for p in platform.list_packages() if p.get("name") == args.name})
    if args.to not in available:
        raise DeployError(f"{args.name} v{args.to} is not uploaded. Available: {available[-10:]}")
    print("==> ROLLBACK to an already-uploaded package (code only; the database is untouched)")
    args.expect_version = None
    return _swap(platform, args, db_name, args.to)


def cmd_delete(args: argparse.Namespace) -> int:
    platform, _, _ = resolve_config(args)
    existing = platform.resolve_instance(args.instance)
    if not existing:
        print(f"no service runs as instance {args.instance!r} — nothing to delete")
        return 0
    print(f"==> deleting {existing['serviceId']} (instance {args.instance}, version {existing['version']})")
    platform.delete_service(existing["serviceId"])
    print("    deleted")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    platform, _, _ = resolve_config(args)
    print(platform.service_status(args.service_id))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--endpoint", help="platform URL (default: ARANGO_ENDPOINT)")
    parser.add_argument("--db", default=None,
                        help="database scope; '' for global (default: ARANGO_DATABASE)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_deploy_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--name", default=DEFAULT_APP_NAME)
        p.add_argument("--instance", default=DEFAULT_INSTANCE)
        p.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
        p.add_argument("--no-ui", action="store_true", help="register as a bare endpoint")
        p.add_argument("--display-name", default=DEFAULT_DISPLAY_NAME)
        p.add_argument("--description", default=DEFAULT_DESCRIPTION)
        p.add_argument("--wait-timeout", type=float, default=900.0)
        p.add_argument("--poll-interval", type=float, default=15.0)

    p = sub.add_parser("list", help="show uploaded packages and deployed services")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("update", help="pre-flight, upload, swap the live service, verify")
    p.add_argument("--version", default=None, help="package version (default: <release>-<next build>)")
    # Resolved lazily: at parser-build time target/ may hold nothing yet, and the
    # newest bundle is the right default once it does.
    p.add_argument("--tarball", default=None,
                   help="bundle to upload (default: newest target/finreflectkg-timetravel-*.tar.gz)")
    add_deploy_args(p)
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("verify", help="poll the public URL until it serves, then deep-check")
    p.add_argument("--instance", default=DEFAULT_INSTANCE)
    p.add_argument("--wait-timeout", type=float, default=900.0)
    p.add_argument("--poll-interval", type=float, default=20.0)
    p.add_argument("--expect-version", default=None, help="assert /healthz reports this release")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("rollback", help="redeploy a previously uploaded package version")
    p.add_argument("--to", required=True, help="package version to go back to")
    add_deploy_args(p)
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("delete", help="remove the deployed service")
    p.add_argument("--instance", default=DEFAULT_INSTANCE)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("status", help="raw status of one service id")
    p.add_argument("--service-id", required=True)
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
