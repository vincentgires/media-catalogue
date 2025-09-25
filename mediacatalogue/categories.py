from dataclasses import dataclass
from collections.abc import Callable


@dataclass
class FileItem():
    path: str
    group: str | None = None


@dataclass
class CollectionItem():
    name: str
    files: list[FileItem]
    collections: list['CollectionItem'] | None = None
    collections_loader: Callable[  # For lazy loading
        ['CollectionItem'], list['CollectionItem']] | None = None

    def get_groups(self) -> list[str]:
        return sorted({f.group for f in self.files if f.group is not None})

    def get_files_in_group(self, group: str) -> list[FileItem]:
        return [f for f in self.files if f.group == group]

    def files_by_group(self) -> dict[str | None, list[FileItem]]:
        grouped: dict[str | None, list[FileItem]] = {}
        for f in self.files:
            if f.group is None:
                continue
            grouped.setdefault(f.group, []).append(f)
        return grouped

    def load_children(self, refresh: bool = False) -> list['CollectionItem']:
        if refresh or self.collections is None:
            if self.collections_loader:
                self.collections = self.collections_loader(self)
        return self.collections or []


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
