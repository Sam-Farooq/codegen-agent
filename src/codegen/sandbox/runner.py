"""Run generated code in a throwaway container.

Nothing the model writes executes on the host. That is not a precaution, it
is the whole reason this is usable: the loop's normal operation is to run
code that is wrong, and some fraction of wrong code deletes things.

The container has no network, a read-only root with one writable tmpfs, a
memory cap, a PID cap and a wall-clock timeout. The PID cap is the one people
leave out, and a fork bomb is a completely ordinary thing for a confused
model to emit.
"""
from __future__ import annotations

import asyncio
import io
import logging
import tarfile
import time

import docker
from docker.errors import ContainerError, ImageNotFound

from codegen.config import get_settings
from codegen.state import FileEdit, SuiteRun

log = logging.getLogger(__name__)


def _tar(files: list[FileEdit]) -> io.BytesIO:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for f in files:
            data = f.content.encode()
            info = tarfile.TarInfo(name=f.path)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    return buffer


class Sandbox:
    def __init__(self, client: docker.DockerClient | None = None):
        self.cfg = get_settings()
        self.client = client or docker.from_env()

    async def run_tests(self, files: list[FileEdit]) -> SuiteRun:
        return await asyncio.to_thread(self._run, files)

    def _run(self, files: list[FileEdit]) -> SuiteRun:
        cfg = self.cfg
        started = time.perf_counter()
        container = None

        try:
            self.client.images.get(cfg.sandbox_image)
        except ImageNotFound:
            log.info("pulling %s", cfg.sandbox_image)
            self.client.images.pull(cfg.sandbox_image)

        try:
            container = self.client.containers.create(
                image=cfg.sandbox_image,
                command=["python", "-m", "pytest", "-q", "--tb=short", "/work"],
                working_dir="/work",
                network_disabled=True,
                mem_limit=f"{cfg.sandbox_memory_mb}m",
                # Without this the memory limit just pushes it into swap and
                # the timeout fires instead, which reads as a different bug.
                memswap_limit=f"{cfg.sandbox_memory_mb}m",
                pids_limit=cfg.sandbox_pids_limit,
                nano_cpus=int(cfg.sandbox_cpu_quota * 1e9),
                read_only=True,
                tmpfs={"/work": "rw,size=32m,exec", "/tmp": "rw,size=16m"},
                user="nobody",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                detach=True,
            )
            container.put_archive("/work", _tar(files))
            container.start()

            try:
                result = container.wait(timeout=cfg.sandbox_timeout_seconds)
                exit_code = result.get("StatusCode", 1)
                timed_out = False
            # docker-py raises several unrelated types on a wait timeout
            # depending on the transport, so this is deliberately broad.
            except Exception:  # noqa: BLE001
                container.kill()
                exit_code, timed_out = 124, True

            stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")

        except ContainerError as exc:
            exit_code, timed_out = exc.exit_status, False
            stdout, stderr = "", str(exc)
        finally:
            if container is not None:
                container.remove(force=True)

        # Truncate from the front. pytest puts the summary last and that is
        # the part the repair prompt actually needs.
        return SuiteRun(
            passed=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout[-8000:],
            stderr=stderr[-4000:],
            duration_s=round(time.perf_counter() - started, 2),
            timed_out=timed_out,
        )
