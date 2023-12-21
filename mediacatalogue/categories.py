from dataclasses import dataclass
from typing import Callable


@dataclass
class CollectionItem():
    name: str
    files: list[str]


@dataclass
class CategoryItem:
    name: str
    family: str
    next: str
    previous: str
    find_history: Callable
    collections: list[CollectionItem]


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


def get_collection_item(item: CategoryItem, name: str):
    for item in item.collections:
        if item.name == name:
            return item
