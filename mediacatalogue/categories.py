from dataclasses import dataclass
from collections.abc import Callable


@dataclass
class FileItem():
    path: str
    group: str | None = None


@dataclass
class CollectionItem():
    name: str
    files: list[FileItem] | None = None
    files_loader: Callable[  # For lazy loading
        [FileItem], list[FileItem]] | None = None
    collections: list['CollectionItem'] | None = None
    collections_loader: Callable[  # For lazy loading
        ['CollectionItem'], list['CollectionItem']] | None = None

    def load_files(self, force: bool = False) -> list[FileItem]:
        if self.files_loader is not None and (self.files is None or force):
            self.files = self.files_loader(self)
        return self.files or []

    def get_groups(self) -> list[str]:
        return sorted({
            f.group for f in self.load_files() if f.group is not None})

    def get_files_in_group(self, group: str) -> list[FileItem]:
        return [f for f in self.load_files() if f.group == group]

    def files_by_group(self) -> dict[str | None, list[FileItem]]:
        grouped: dict[str | None, list[FileItem]] = {}
        for f in self.load_files():
            if f.group is None:
                continue
            grouped.setdefault(f.group, []).append(f)
        return grouped

@dataclass
class CategoryItem:
    name: str
    family: str
    next: str
    previous: str
    find_history: Callable
    collections: list[CollectionItem]
    expand_group: bool = False


categories: list[CategoryItem] = []


def get_categories_by_family() -> dict:
    result = {}
    if categories is None:
        return result
    for category in categories:
        family = category.family
        if family not in result:
            result[family] = []
        result[family].append(category)
    return result


def get_category_item(name: str) -> CategoryItem:
    if categories is None:
        return
    for item in categories:
        if item.name == name:
            return item
