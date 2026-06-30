# -*- coding: utf-8 -*-
"""
脚本名称：
    01_download_roads_by_place.py

功能：
    按行政边界 / 地名，从 OpenStreetMap 下载道路中心线数据。

适合场景：
    你想获取某个城市、区县、街道等行政范围内的道路数据。
    例如：广州市越秀区、大连市中山区、北京市朝阳区。

你需要自己填写 / 修改的内容：
    1. PLACE_QUERY：
       你要查询的行政区或地名。

    2. WHICH_RESULT：
       如果地名匹配结果不对，可以尝试改成 1、2、3。

    3. NETWORK_TYPE：
       道路类型，街景采样一般建议使用 "drive"。

输出文件：
    output_by_place/
        ├─ boundary_used.gpkg        实际识别到的行政边界
        ├─ roads_wgs84.gpkg          经纬度道路数据，EPSG:4326
        ├─ roads_projected.gpkg      米制投影道路数据，适合后续按距离采样
        ├─ nodes_wgs84.gpkg          经纬度节点数据
        ├─ nodes_projected.gpkg      投影节点数据
        ├─ graph_raw.gpkg            OSMnx 原始图网络
        ├─ graph_raw.graphml         OSMnx 图网络文件
        └─ preview.png               预览图
"""

from pathlib import Path
import json

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # 使用非交互式后端，只保存图片，不弹出绘图窗口
import matplotlib.pyplot as plt
import osmnx as ox


# ============================================================
# 1. 需要你自己填写 / 修改的参数
# ============================================================

# 你要获取的行政区 / 地名。
# 推荐写完整层级，越完整越不容易匹配错。
# 英文示例：
# PLACE_QUERY = "Yuexiu District, Guangzhou, Guangdong, China"
#
# 中文示例：
# PLACE_QUERY = "中国 广东省 广州市 越秀区"
PLACE_QUERY = "Guangzhou, Guangdong, China"


# 如果 OSMnx 识别的边界不对，可以尝试把 None 改成 1、2、3。
# None 表示自动选择第一个合适的 Polygon / MultiPolygon。
WHICH_RESULT = None


# 道路网络类型。
# "drive"：机动车道路，最适合百度街景采样。
# "walk"：步行网络。
# "bike"：自行车网络。
# "all"：所有道路，比较杂。
# "all_public"：所有公共道路。
NETWORK_TYPE = "drive"


# 输出文件夹。
OUT_DIR = Path("roads_output_广州市")

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
RETAIN_ALL = False


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
    # 后续做街景采样时，这个 road_id 会很方便。
    if id_name not in gdf_clean.columns:
        gdf_clean.insert(0, id_name, range(1, len(gdf_clean) + 1))

    # 把复杂字段转成字符串。
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
        1. 根据地名查询行政边界。
        2. 打印识别结果，方便你核对是不是想要的区域。
        3. 用识别到的边界下载道路网络。
        4. 导出 WGS84 道路、投影道路、节点、边界和预览图。
    """

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("开始按行政边界 / 地名下载 OSM 道路数据")
    print(f"查询地名：{PLACE_QUERY}")
    print(f"道路类型：{NETWORK_TYPE}")

    # ------------------------------------------------------------
    # 4.1 先通过地名获取行政边界
    # ------------------------------------------------------------

    area_gdf = ox.geocoder.geocode_to_gdf(
        PLACE_QUERY,
        which_result=WHICH_RESULT
    )

    print("\n地名识别结果如下，请先检查是不是你想要的区域：")

    check_cols = [
        col for col in
        ["display_name", "osm_type", "osm_id", "class", "type"]
        if col in area_gdf.columns
    ]

    print(area_gdf[check_cols])

    # 提取行政边界 polygon。
    polygon = area_gdf.geometry.iloc[0]

    # ------------------------------------------------------------
    # 4.2 根据行政边界下载道路网络
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

    # 后续如果要“每隔 50 米生成一个街景采样点”，必须使用米制坐标。
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
    # 4.6 保存本次使用的行政边界
    # ------------------------------------------------------------

    area_gdf.to_file(
        OUT_DIR / "boundary_used.gpkg",
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

    ax.set_title("OSM Roads by Place")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "preview.png", dpi=300)
    plt.close()

    print("\n全部完成")
    print(f"输出文件夹：{OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()