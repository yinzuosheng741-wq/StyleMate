"""Shared category heuristics for both chat tools and the wardrobe workbench."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutfitCategories:
    top: str
    bottom: str
    shoes: str
    avoid: str


def outfit_categories(temperature: float | None) -> OutfitCategories:
    if temperature is None:
        return OutfitCategories("适合场景且便于增减的上装", "便于活动的下装", "适合活动的鞋履", "在温度未知时直接确定衣物厚薄")
    if temperature >= 28:
        return OutfitCategories("透气短袖或亚麻衬衫", "轻薄下装（长裤或五分裤）", "透气运动鞋或凉鞋", "厚外套、厚针织和不透气面料")
    if temperature <= 12:
        return OutfitCategories("保暖内层+针织衫", "厚长裤", "短靴或防滑运动鞋", "单层薄款上装和露踝鞋履")
    return OutfitCategories("长袖衬衫或薄针织", "直筒长裤", "休闲鞋或乐福鞋", "过多厚重层次")
