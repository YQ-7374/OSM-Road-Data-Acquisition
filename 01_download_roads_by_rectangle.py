# -*- coding: utf-8 -*-
"""
脚本名称：
    02_download_roads_by_bbox.py

功能：
    按矩形框 bbox，从 OpenStreetMap 下载道路中心线数据。

适合场景：
    你想快速获取一个矩形片区内的道路。
    比如某个研究区、街区、校园、城市中心片区。

你需要自己填写 / 修改的内容：
    1. WEST：
       左边界经度。

    2. SOUTH：
       下边界纬度。

    3. EAST：
       右边界经度。

    4. NORTH：
       上边界纬度。

注意：
    OSMnx 2.x 中 bbox 顺序是：
        (left, bottom, right, top)
    也就是：
        (west, south, east, north)

输出文件：
    output_by_bbox/
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
from shapely.geometry import box


# ============================================================
# 1. 需要你自己填写 / 修改的参数
# ============================================================

# 矩形框四至坐标，坐标系必须是 WGS84 经纬度，EPSG:4326。
# WEST：左边界经度
# SOUTH：下边界纬度
# EAST：右边界经度
# NORTH：上边界纬度
#
# 下面只是示例值，请换成你自己的研究范围。
WEST = 113.250
SOUTH = 23.110
EAST = 113.300
NORTH = 23.150


# 道路网络类型。
# 街景采样一般建议使用 "drive"。
NETWORK_TYPE = "drive"


# 输出文件夹。
OUT_DIR = Path("output_by_bbox")


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
        1. 构造 bbox。
        2. 下载 bbox 范围内的 OSM 道路网络。
        3. 保存 WGS84 道路和米制投影道路。
        4. 保存矩形边界和预览图。
    """

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始按矩形框 bbox 下载 OSM 道路数据")
    print(f"WEST  = {WEST}")
    print(f"SOUTH = {SOUTH}")
    print(f"EAST  = {EAST}")
    print(f"NORTH = {NORTH}")
    print(f"道路类型：{NETWORK_TYPE}")

    # ------------------------------------------------------------
    # 4.1 构造 bbox
    # ------------------------------------------------------------

    # OSMnx 2.x 的 bbox 顺序：
    # (left, bottom, right, top)
    # 也就是：
    # (west, south, east, north)
    bbox = (WEST, SOUTH, EAST, NORTH)

    # ------------------------------------------------------------
    # 4.2 根据 bbox 下载道路网络
    # ------------------------------------------------------------

    G = ox.graph.graph_from_bbox(
        bbox,
        network_type=NETWORK_TYPE,
        simplify=SIMPLIFY,
        retain_all=RETAIN_ALL,
        truncate_by_edge=TRUNCATE_BY_EDGE
    )

    print("\n道路网络下载完成")
    print(f"节点数量：{len(G.nodes)}")
    print(f"道路边数量：{len(G.edges)}")

    # ------------------------------------------------------------
    # 4.3 创建矩形边界，方便保存和预览
    # ------------------------------------------------------------

    boundary_polygon = box(WEST, SOUTH, EAST, NORTH)

    area_gdf = gpd.GeoDataFrame(
        {
            "source": ["bbox"],
            "west": [WEST],
            "south": [SOUTH],
            "east": [EAST],
            "north": [NORTH]
        },
        geometry=[boundary_polygon],
        crs="EPSG:4326"
    )

    # ------------------------------------------------------------
    # 4.4 保存 OSMnx 原始图网络
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
    # 4.5 转为 GeoDataFrame，保存 WGS84 道路
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
    # 4.6 转为米制投影坐标，保存投影道路
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
    # 4.7 保存矩形边界
    # ------------------------------------------------------------

    area_gdf.to_file(
        OUT_DIR / "boundary_used.gpkg",
        layer="boundary",
        driver="GPKG"
    )

    # ------------------------------------------------------------
    # 4.8 绘制预览图
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

    ax.set_title("OSM Roads by BBOX")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "preview.png", dpi=300)
    plt.close()

    print("\n全部完成")
    print(f"输出文件夹：{OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()