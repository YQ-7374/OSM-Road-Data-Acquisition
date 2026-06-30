# -*- coding: utf-8 -*-
"""
脚本名称：
    01_download_roads_by_center_radius.py

功能：
    以某一坐标点为中心，按照指定半径，从 OpenStreetMap 下载道路中心线数据。

适合场景：
    你想获取某个点周边一定范围内的道路数据。
    例如：
        某个地铁站周边 1000m
        某个历史街区核心点周边 800m
        某个学校、商圈、医院周边 1500m

你需要自己填写 / 修改的内容：
    1. CENTER_LNG / CENTER_LAT：
       中心点经纬度。

    2. RADIUS_M：
       半径，单位为米。

    3. NETWORK_TYPE：
       道路类型，街景采样一般建议使用 "drive"。

    4. OUT_DIR：
       输出文件夹。

重要说明：
    本脚本只使用 OSM / WGS84 坐标。
    如果你的中心点来自百度地图，需要先转换为 WGS84 后再填入本脚本。

输出文件：
    output_by_center_radius/
        ├─ boundary_used_wgs84.gpkg          WGS84 圆形研究边界
        ├─ boundary_used_projected.gpkg      米制投影圆形研究边界
        ├─ roads_wgs84.gpkg                  WGS84 道路数据，EPSG:4326
        ├─ roads_projected.gpkg              米制投影道路数据，适合后续按距离采样
        ├─ nodes_wgs84.gpkg                  WGS84 节点数据
        ├─ nodes_projected.gpkg              投影节点数据
        ├─ graph_raw.gpkg                    OSMnx 原始图网络
        ├─ graph_raw.graphml                 OSMnx 图网络文件
        └─ preview.png                       预览图

后续流程：
    01_download_roads_by_center_radius.py
        ↓
    02_generate_streetview_sample_points.py
        ↓
    03_convert_sample_points_to_baidu_coords.py
        ↓
    下载百度街景影像
"""


from pathlib import Path
import json

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # 使用非交互式后端，只保存图片，不弹出绘图窗口
import matplotlib.pyplot as plt
import osmnx as ox
from shapely.geometry import Point


# ============================================================
# 1. 需要你自己填写 / 修改的参数
# ============================================================

# ------------------------------------------------------------
# 1.1 中心点坐标
# ------------------------------------------------------------

# 中心点经纬度。
# 注意：
#   这里必须填写 WGS84 经纬度。
#   也就是 OSM / GPS / QGIS / ArcGIS 常用坐标。
#
# 顺序是：
#   经度 lng
#   纬度 lat
#
# 示例：广州市某点
CENTER_LNG = 113.296996
CENTER_LAT = 23.136993


# ------------------------------------------------------------
# 1.2 半径设置
# ------------------------------------------------------------

# 半径，单位：米。
# 常见取值：
#   500：小街区
#   1000：步行生活圈
#   1500：站点周边扩展范围
RADIUS_M = 1000


# ------------------------------------------------------------
# 1.3 OSM 道路类型
# ------------------------------------------------------------

# 道路网络类型。
# "drive"：机动车道路，最适合街景采样。
# "drive_service"：机动车道路 + 服务道路，更细。
# "walk"：步行网络。
# "bike"：自行车网络。
# "all"：所有道路，比较杂。
# "all_public"：所有公共道路。
NETWORK_TYPE = "drive_service"


# ------------------------------------------------------------
# 1.4 输出文件夹
# ------------------------------------------------------------

# 这里可以自己改成不同研究区的输出文件夹。
# 例如：
# OUT_DIR = Path("roads_output_广州越秀_中心点1000m")
# OUT_DIR = Path("roads_output_大连中山广场_800m")
OUT_DIR = Path("越秀区_半圆_osmroad")


# ============================================================
# 2. 一般不用改的参数
# ============================================================

# 是否简化道路拓扑。
# True：合并道路中间形状点，让路网更接近“路段”。
# False：保留更多原始节点。
SIMPLIFY = True


# 是否保留所有连通子图。
# False：只保留最大连通网络，结果更干净。
# True：保留所有零散道路，适合小范围或路网不连续区域。
RETAIN_ALL = True


# 是否保留跨越边界的道路边。
# True：边界附近的道路保留更完整。
TRUNCATE_BY_EDGE = True


# OSMnx 设置。
# use_cache=True：缓存请求，重复运行时更快。
# log_console=True：在命令行显示运行日志。
ox.settings.use_cache = True
ox.settings.log_console = True
ox.settings.requests_timeout = 180


# ============================================================
# 3. 工具函数：清理字段，方便导出为 GPKG
# ============================================================

def make_json_serializable(value):
    """
    把 list / dict / tuple / set 等复杂字段转成字符串。

    原因：
        OSM 数据中有些字段可能是列表。
        例如一条道路可能有多个 name 或多个 highway 标签。
        GeoPackage / Shapefile 对复杂字段支持不好，
        如果不处理，导出时可能报错。
    """
    if isinstance(value, (list, dict, tuple, set)):
        return json.dumps(value, ensure_ascii=False)

    return value


def clean_gdf_for_export(gdf: gpd.GeoDataFrame, id_name: str) -> gpd.GeoDataFrame:
    """
    清理 GeoDataFrame，便于保存成 GIS 文件。

    参数：
        gdf:
            OSMnx 转出来的 GeoDataFrame。

        id_name:
            新增 ID 字段名。
            道路用 road_id，节点用 node_id。

    返回：
        清理后的 GeoDataFrame。
    """

    # 复制一份，避免修改原始数据。
    gdf_clean = gdf.copy()

    # OSMnx 的 edges 通常使用多级索引 u、v、key。
    # reset_index 后，u、v、key 会变成普通字段，方便查看和导出。
    gdf_clean = gdf_clean.reset_index()

    # 新增一个从 1 开始的连续编号。
    if id_name not in gdf_clean.columns:
        gdf_clean.insert(0, id_name, range(1, len(gdf_clean) + 1))

    # 把复杂字段转成字符串。
    for col in gdf_clean.columns:
        if col == gdf_clean.geometry.name:
            continue

        gdf_clean[col] = gdf_clean[col].apply(make_json_serializable)

    return gdf_clean


def build_circle_boundary(center_lng: float, center_lat: float, radius_m: float) -> tuple:
    """
    根据中心点和半径生成圆形研究边界。

    为什么要先投影？
        经纬度单位是“度”，不能直接 buffer 1000 米。
        所以需要先把中心点投影到米制坐标系，再 buffer。

    返回：
        area_wgs84:
            WGS84 圆形边界。

        area_projected:
            米制投影圆形边界。
    """

    # 构建中心点 GeoDataFrame。
    center_gdf = gpd.GeoDataFrame(
        [{
            "name": f"center_radius_{int(radius_m)}m",
            "center_lng_wgs84": center_lng,
            "center_lat_wgs84": center_lat,
            "radius_m": radius_m,
            "geometry": Point(center_lng, center_lat)
        }],
        geometry="geometry",
        crs="EPSG:4326"
    )

    # 自动估计合适的 UTM 投影坐标系。
    projected_crs = center_gdf.estimate_utm_crs()

    if projected_crs is None:
        projected_crs = "EPSG:3857"

    print(f"\n自动选择的圆形边界投影坐标系：{projected_crs}")

    # 转为米制坐标。
    center_projected = center_gdf.to_crs(projected_crs)

    # 在米制坐标中 buffer 半径。
    area_projected = center_projected.copy()
    area_projected["geometry"] = area_projected.geometry.buffer(radius_m)

    # 转回 WGS84，供 OSMnx 下载道路使用。
    area_wgs84 = area_projected.to_crs("EPSG:4326")

    return area_wgs84, area_projected


# ============================================================
# 4. 主程序
# ============================================================

def main():
    """
    主流程：
        1. 读取中心点 WGS84 坐标。
        2. 根据中心点和半径生成圆形边界。
        3. 用圆形边界下载 OSM 道路网络。
        4. 导出 WGS84 道路、投影道路、节点、边界和预览图。
    """

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始按中心点 + 半径下载 OSM 道路数据")
    print(f"中心点 WGS84 坐标：({CENTER_LNG}, {CENTER_LAT})")
    print(f"半径：{RADIUS_M} m")
    print(f"道路类型：{NETWORK_TYPE}")
    print(f"输出文件夹：{OUT_DIR}")

    # ------------------------------------------------------------
    # 4.1 根据中心点和半径生成圆形研究边界
    # ------------------------------------------------------------

    area_gdf, area_projected = build_circle_boundary(
        center_lng=CENTER_LNG,
        center_lat=CENTER_LAT,
        radius_m=RADIUS_M
    )

    polygon = area_gdf.geometry.iloc[0]

    # ------------------------------------------------------------
    # 4.2 根据圆形边界下载道路网络
    # ------------------------------------------------------------

    print("\n开始从 OSM 下载道路网络...")

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
    # 4.3 保存 OSMnx 原始图网络
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
    # 4.4 转为 GeoDataFrame，并保存 WGS84 经纬度道路
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
    # 4.5 投影为米制坐标，并保存投影道路
    # ------------------------------------------------------------

    # 后续如果要“每隔 30 米生成一个街景采样点”，必须使用米制坐标。
    G_projected = ox.projection.project_graph(G)

    nodes_projected, edges_projected = ox.convert.graph_to_gdfs(G_projected)

    print(f"\n自动选择的道路投影坐标系：{edges_projected.crs}")

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
    # 4.6 保存本次使用的圆形边界
    # ------------------------------------------------------------

    area_gdf.to_file(
        OUT_DIR / "boundary_used_wgs84.gpkg",
        layer="boundary",
        driver="GPKG"
    )

    area_projected.to_file(
        OUT_DIR / "boundary_used_projected.gpkg",
        layer="boundary",
        driver="GPKG"
    )

    # ------------------------------------------------------------
    # 4.7 绘制预览图
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

    ax.scatter(
        [CENTER_LNG],
        [CENTER_LAT],
        s=20,
        marker="o"
    )

    ax.set_title(f"OSM Roads within {RADIUS_M}m Radius")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "preview.png", dpi=300)
    plt.close()

    print("\n全部完成")
    print(f"输出文件夹：{OUT_DIR.resolve()}")
    print("\n主要输出：")
    print(f"  WGS84 道路：{OUT_DIR / 'roads_wgs84.gpkg'}")
    print(f"  投影道路：{OUT_DIR / 'roads_projected.gpkg'}")
    print(f"  WGS84 节点：{OUT_DIR / 'nodes_wgs84.gpkg'}")
    print(f"  投影节点：{OUT_DIR / 'nodes_projected.gpkg'}")
    print(f"  圆形边界：{OUT_DIR / 'boundary_used_wgs84.gpkg'}")
    print(f"  预览图：{OUT_DIR / 'preview.png'}")


if __name__ == "__main__":
    main()