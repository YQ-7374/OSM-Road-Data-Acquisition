# -*- coding: utf-8 -*-
"""
脚本名称：
    03_download_roads_by_polygon.py

功能：
    按自己画的 polygon 边界，从 OpenStreetMap 下载道路中心线数据。

适合场景：
    你已经在 QGIS / ArcGIS 中画好了研究区边界。
    比如历史街区边界、城市更新单元、校园边界、控规片区边界。

你需要自己填写 / 修改的内容：
    1. POLYGON_FILE：
       你的研究区边界文件路径。

    2. POLYGON_LAYER：
       如果是 GeoPackage 且里面有多个图层，需要填写图层名。
       如果是 shp / geojson，通常保持 None。

    3. NETWORK_TYPE：
       道路类型，街景采样一般建议使用 "drive"。

输入边界格式：
    支持：
        .shp
        .gpkg
        .geojson

注意：
    1. 文件必须是面要素 Polygon / MultiPolygon。
    2. 文件必须有坐标系。
    3. 如果不是 EPSG:4326，代码会自动转换成 EPSG:4326。
    4. 如果文件里有多个 polygon，代码会自动合并。

输出文件：
    output_by_polygon/
        ├─ boundary_used.gpkg
        ├─ roads_wgs84.gpkg
        ├─ roads_projected.gpkg
        ├─ nodes_wgs84.gpkg
        ├─ nodes_projected.gpkg
        ├─ graph_raw.gpkg
        ├─ graph_raw.graphml
        └─ preview.png
"""

from pathlib import Path
import json

import geopandas as gpd
import matplotlib.pyplot as plt
import osmnx as ox


# ============================================================
# 1. 需要你自己填写 / 修改的参数
# ============================================================

# 你的研究区边界文件。
# 可以是 shp、gpkg 或 geojson。
#
# 示例：
# POLYGON_FILE = "study_area.shp"
# POLYGON_FILE = "study_area.gpkg"
# POLYGON_FILE = "study_area.geojson"
POLYGON_FILE = "study_area.gpkg"


# 如果 POLYGON_FILE 是 GeoPackage，并且里面有多个图层，需要指定图层名。
# 例如：
# POLYGON_LAYER = "boundary"
#
# 如果是 shp 或 geojson，通常保持 None。
POLYGON_LAYER = None


# 道路网络类型。
# 街景采样一般建议使用 "drive"。
NETWORK_TYPE = "drive"


# 输出文件夹。
OUT_DIR = Path("output_by_polygon")


# ============================================================
# 2. 一般不用改的参数
# ============================================================

SIMPLIFY = True
RETAIN_ALL = False
TRUNCATE_BY_EDGE = True

ox.settings.use_cache = True
ox.settings.log_console = True
ox.settings.requests_timeout = 180


# ============================================================
# 3. 工具函数：清理字段，方便导出为 GPKG
# ============================================================

def make_json_serializable(value):
    """
    把复杂字段转成字符串，避免导出 GeoPackage 时报错。
    """
    if isinstance(value, (list, dict, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    return value


def clean_gdf_for_export(gdf: gpd.GeoDataFrame, id_name: str) -> gpd.GeoDataFrame:
    """
    清理 GeoDataFrame，添加连续编号，并把复杂字段转成字符串。
    """

    gdf_clean = gdf.copy()
    gdf_clean = gdf_clean.reset_index()

    if id_name not in gdf_clean.columns:
        gdf_clean.insert(0, id_name, range(1, len(gdf_clean) + 1))

    for col in gdf_clean.columns:
        if col == gdf_clean.geometry.name:
            continue
        gdf_clean[col] = gdf_clean[col].apply(make_json_serializable)

    return gdf_clean


# ============================================================
# 4. 主程序
# ============================================================

def main():
    """
    主流程：
        1. 读取自己画的 polygon 文件。
        2. 检查坐标系。
        3. 自动转为 EPSG:4326。
        4. 合并多个 polygon。
        5. 下载 polygon 范围内的 OSM 道路网络。
        6. 保存 WGS84 道路、投影道路、边界和预览图。
    """

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始按自定义 polygon 下载 OSM 道路数据")
    print(f"边界文件：{POLYGON_FILE}")
    print(f"图层名称：{POLYGON_LAYER}")
    print(f"道路类型：{NETWORK_TYPE}")

    polygon_path = Path(POLYGON_FILE)

    if not polygon_path.exists():
        raise FileNotFoundError(
            f"没有找到边界文件：{POLYGON_FILE}\n"
            "请检查 POLYGON_FILE 路径是否正确。"
        )

    # ------------------------------------------------------------
    # 4.1 读取 polygon 文件
    # ------------------------------------------------------------

    if POLYGON_LAYER is not None:
        area_gdf = gpd.read_file(
            polygon_path,
            layer=POLYGON_LAYER
        )
    else:
        area_gdf = gpd.read_file(polygon_path)

    if area_gdf.empty:
        raise ValueError(
            "读取到的 polygon 文件为空，请检查边界文件。"
        )

    # ------------------------------------------------------------
    # 4.2 检查坐标系
    # ------------------------------------------------------------

    if area_gdf.crs is None:
        raise ValueError(
            "你的 polygon 文件没有坐标系信息。\n"
            "请先在 QGIS / ArcGIS 中定义坐标系。"
        )

    print(f"\n原始坐标系：{area_gdf.crs}")

    # ------------------------------------------------------------
    # 4.3 转成 EPSG:4326 经纬度
    # ------------------------------------------------------------

    # OSMnx 请求 OSM 数据时，边界通常需要使用 WGS84 经纬度。
    area_gdf = area_gdf.to_crs(epsg=4326)

    print("已转换为 EPSG:4326")

    # 删除空几何。
    area_gdf = area_gdf[area_gdf.geometry.notna()].copy()

    if area_gdf.empty:
        raise ValueError(
            "删除空几何后，polygon 文件没有有效几何。"
        )

    # ------------------------------------------------------------
    # 4.4 合并多个 polygon
    # ------------------------------------------------------------

    # 如果边界文件里有多个面，比如多个街区单元，
    # 这里会把它们合并成一个 MultiPolygon 或 Polygon。
    try:
        polygon = area_gdf.geometry.union_all()
    except AttributeError:
        polygon = area_gdf.geometry.unary_union

    if polygon.is_empty:
        raise ValueError(
            "合并后的 polygon 为空，请检查边界文件。"
        )

    # 用合并后的边界重新构造 area_gdf，方便后续保存。
    area_gdf = gpd.GeoDataFrame(
        {"source": ["custom_polygon"]},
        geometry=[polygon],
        crs="EPSG:4326"
    )

    # ------------------------------------------------------------
    # 4.5 根据 polygon 下载道路网络
    # ------------------------------------------------------------

    G = ox.graph.graph_from_polygon(
        polygon,
        network_type=NETWORK_TYPE,
        simplify=SIMPLIFY,
        retain_all=RETAIN_ALL,
        truncate_by_edge=TRUNCATE_BY_EDGE
    )

    print("\n道路网络下载完成")
    print(f"节点数量：{len(G.nodes)}")
    print(f"道路边数量：{len(G.edges)}")

    # ------------------------------------------------------------
    # 4.6 保存 OSMnx 原始图网络
    # ------------------------------------------------------------

    ox.io.save_graph_geopackage(
        G,
        filepath=OUT_DIR / "graph_raw.gpkg",
        directed=False
    )

    ox.io.save_graphml(
        G,
        filepath=OUT_DIR / "graph_raw.graphml"
    )

    # ------------------------------------------------------------
    # 4.7 转为 GeoDataFrame，保存 WGS84 道路
    # ------------------------------------------------------------

    nodes_wgs84, edges_wgs84 = ox.convert.graph_to_gdfs(G)

    edges_wgs84_clean = clean_gdf_for_export(
        edges_wgs84,
        id_name="road_id"
    )

    nodes_wgs84_clean = clean_gdf_for_export(
        nodes_wgs84,
        id_name="node_id"
    )

    edges_wgs84_clean.to_file(
        OUT_DIR / "roads_wgs84.gpkg",
        layer="roads",
        driver="GPKG"
    )

    nodes_wgs84_clean.to_file(
        OUT_DIR / "nodes_wgs84.gpkg",
        layer="nodes",
        driver="GPKG"
    )

    # ------------------------------------------------------------
    # 4.8 转为米制投影坐标，保存投影道路
    # ------------------------------------------------------------

    G_projected = ox.projection.project_graph(G)

    nodes_projected, edges_projected = ox.convert.graph_to_gdfs(G_projected)

    print(f"\n自动选择的投影坐标系：{edges_projected.crs}")

    edges_projected_clean = clean_gdf_for_export(
        edges_projected,
        id_name="road_id"
    )

    nodes_projected_clean = clean_gdf_for_export(
        nodes_projected,
        id_name="node_id"
    )

    edges_projected_clean.to_file(
        OUT_DIR / "roads_projected.gpkg",
        layer="roads",
        driver="GPKG"
    )

    nodes_projected_clean.to_file(
        OUT_DIR / "nodes_projected.gpkg",
        layer="nodes",
        driver="GPKG"
    )

    # ------------------------------------------------------------
    # 4.9 保存本次实际使用的边界
    # ------------------------------------------------------------

    area_gdf.to_file(
        OUT_DIR / "boundary_used.gpkg",
        layer="boundary",
        driver="GPKG"
    )

    # ------------------------------------------------------------
    # 4.10 绘制预览图
    # ------------------------------------------------------------

    fig, ax = plt.subplots(figsize=(8, 8))

    area_gdf.boundary.plot(
        ax=ax,
        linewidth=1.5
    )

    edges_wgs84.plot(
        ax=ax,
        linewidth=0.5
    )

    ax.set_title("OSM Roads by Custom Polygon")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "preview.png", dpi=300)
    plt.close()

    print("\n全部完成")
    print(f"输出文件夹：{OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()