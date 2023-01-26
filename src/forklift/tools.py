from typing import Callable, Dict

__all__ = [
    "get_tool_runner",
    "ToolExceptionBase",
    "InvalidToolName",
    "UnsupportedTool",
]


def run_black() -> None:
    """Run black."""
    from black import patched_main

    patched_main()


def run_isort() -> None:
    """Run isort."""
    from isort.main import main

    main()


def run_flake8() -> None:
    from flake8.main.cli import main

    main()


runners: Dict[str, Callable[[], None]] = {
    "black": run_black,
    "isort": run_isort,
    "flake8": run_flake8,
}


class ToolExceptionBase(Exception):
    """Exception raised for CLI tool-related exceptions."""

    tool_name: str

    def __init__(self, tool_name) -> None:
        super().__init__(tool_name)
        self.tool_name = tool_name


class UnsupportedTool(ToolExceptionBase):
    """Exception raised for unsupported CLI tools."""

    def __str__(self) -> str:
        return f"Unsupported tool: {self.tool_name}"


class InvalidToolName(ToolExceptionBase):
    """Exception raised for unsupported CLI tools."""

    def __str__(self) -> str:
        return f"Invalid tool name: {self.tool_name}"


def get_tool_runner(tool_name: str) -> Callable[[], None]:
    """Get a runner function for a CLI tool."""
    tool_name = tool_name.strip().lower()
    if "/" in tool_name or "\\" in tool_name:
        raise InvalidToolName(tool_name=tool_name)
    try:
        return runners[tool_name]
    except KeyError:
        raise UnsupportedTool(tool_name=tool_name)
