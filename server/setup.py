"""Include the canonical protocol contracts in wheels and source distributions."""

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).parent.resolve()


def contracts_source():
    # An sdist contains its own copy; a checkout uses the repository's contracts.
    for candidate in (ROOT / "contracts", ROOT.parent / "contracts"):
        if (candidate / "protocol.json").is_file():
            return candidate
    raise RuntimeError("Protocol contracts are missing; refusing an incomplete build.")


def copy_contracts(destination):
    source = contracts_source()
    for path in source.rglob("*.json"):
        target = Path(destination) / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


class BuildWithContracts(build_py):
    def run(self):
        super().run()
        copy_contracts(Path(self.build_lib) / "rhinomcp" / "contracts")


class SourceWithContracts(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        copy_contracts(Path(base_dir) / "contracts")


setup(cmdclass={"build_py": BuildWithContracts, "sdist": SourceWithContracts})
