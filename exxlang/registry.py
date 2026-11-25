"""Discover built-in modules and resolve registered compiler components by name."""

from importlib import import_module
from pkgutil import iter_modules


class Registry:
    def __init__(self, package):
        self.package = package
        self.classes = {}
        self.loaded = False

    def register(self, cls):
        if cls.name in self.classes:
            raise ValueError(f"duplicate {self.package} registration: {cls.name}")
        self.classes[cls.name] = cls
        return cls

    def names(self):
        if not self.loaded:
            package = import_module(self.package)
            for module in iter_modules(package.__path__, package.__name__ + "."):
                import_module(module.name)
            self.loaded = True
        return tuple(sorted(self.classes))

    def create(self, name=None):
        names = self.names()
        if name is None and len(names) == 1:
            name = names[0]
        if name not in self.classes:
            raise ValueError(f"select a registered {self.package.rsplit('.', 1)[-1]} entry "
                             f"({', '.join(names)}), got {name!r}")
        return self.classes[name]()


platforms = Registry("exxlang.platforms")
targets = Registry("exxlang.targets")
