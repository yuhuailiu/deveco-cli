from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class DevEcoNotFoundError(Exception):
    pass


class ProjectNotFoundError(Exception):
    pass


_DEVECO_DEFAULT = Path("/Applications/DevEco-Studio.app")


def _resolve_deveco_path() -> Path:
    env = os.environ.get("DEVECO_PATH")
    if env:
        p = Path(env)
        if p.exists():
            return p
        raise DevEcoNotFoundError(f"DEVECO_PATH 指定的路径不存在: {p}")
    if _DEVECO_DEFAULT.exists():
        return _DEVECO_DEFAULT
    raise DevEcoNotFoundError(
        f"未找到 DevEco Studio。请设置 DEVECO_PATH 环境变量，"
        f"或将 DevEco Studio 安装到默认路径 {_DEVECO_DEFAULT}"
    )


@dataclass
class DevEcoConfig:
    deveco_path: Path
    project_path: Path

    def _c(self) -> Path:
        return self.deveco_path / "Contents"

    @property
    def node(self) -> Path:
        p = self._c() / "tools" / "node" / "bin" / "node"
        if not p.exists():
            raise FileNotFoundError(f"Node.js 未找到: {p}")
        return p

    @property
    def ohpm(self) -> Path:
        p = self._c() / "tools" / "ohpm" / "bin" / "ohpm"
        if not p.exists():
            raise FileNotFoundError(f"ohpm 未找到: {p}")
        return p

    @property
    def hvigorw_js(self) -> Path:
        p = self._c() / "tools" / "hvigor" / "bin" / "hvigorw.js"
        if not p.exists():
            raise FileNotFoundError(f"hvigorw.js 未找到: {p}")
        return p

    @property
    def hdc(self) -> Path:
        p = self._c() / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
        if not p.exists():
            raise FileNotFoundError(f"hdc 未找到: {p}")
        return p

    @property
    def sdk_home(self) -> Path:
        """DEVECO_SDK_HOME — hvigorw 依赖的 SDK 根目录"""
        return self._c() / "sdk"

    @property
    def sdk_ets_api(self) -> Path:
        """SDK ArkTS 声明文件目录，ace-server 的 sdkJsPath"""
        return self._c() / "sdk" / "default" / "openharmony" / "ets" / "api"

    @property
    def ace_loader(self) -> Path:
        """ace-loader 路径，ace-server 的 aceLoaderPath"""
        return self._c() / "sdk" / "default" / "openharmony" / "js" / "build-tools" / "ace-loader"

    @property
    def ace_server(self) -> Path:
        # 已知路径
        candidate = self._c() / "plugins" / "openharmony" / "ace-server" / "out" / "index.js"
        if candidate.exists():
            return candidate
        # glob 兜底
        results = list((self._c() / "plugins").glob("**/ace-server/out/index.js"))
        if results:
            return results[0]
        raise FileNotFoundError(
            f"ace-server 未找到（搜索路径: {self._c() / 'plugins'}）"
        )


def get_config(project: Path | str) -> DevEcoConfig:
    deveco = _resolve_deveco_path()
    project_path = Path(project).resolve()
    if not project_path.exists():
        raise ProjectNotFoundError(f"工程路径不存在: {project_path}")
    return DevEcoConfig(deveco_path=deveco, project_path=project_path)


def get_hdc() -> Path:
    deveco = _resolve_deveco_path()
    p = deveco / "Contents" / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    if not p.exists():
        raise FileNotFoundError(f"hdc 未找到: {p}")
    return p
