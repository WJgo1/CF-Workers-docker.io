"""按 "module:function" 或 "path/to/file.py:function" 加载分析插件。"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .base import Analyzer


def _load_module_from_file(file_path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件文件: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    # 允许插件文件 import 同目录下的其他模块
    parent = str(file_path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec.loader.exec_module(module)
    return module


def load_analyzer(spec: str) -> Analyzer:
    if ":" not in spec:
        raise ValueError(f"分析插件格式应为 module:function 或 path.py:function，当前为: {spec}")
    target, func_name = spec.rsplit(":", 1)
    target = target.strip()
    func_name = func_name.strip()
    if not target or not func_name:
        raise ValueError(f"分析插件格式错误: {spec}")

    path_obj = Path(target).expanduser()
    if target.endswith(".py") or path_obj.is_file():
        file_path = path_obj.resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"找不到插件文件: {file_path}")
        module_name = f"reliability_plugin_{file_path.stem}_{abs(hash(str(file_path))) % 10**8}"
        module = _load_module_from_file(file_path, module_name)
    else:
        module = importlib.import_module(target)

    func = getattr(module, func_name, None)
    if func is None or not callable(func):
        raise AttributeError(f"插件 {target} 中不存在可调用对象 {func_name}")
    return func
