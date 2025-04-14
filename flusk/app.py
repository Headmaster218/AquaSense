import base64
import io
from flask import Flask, render_template, jsonify, send_from_directory, url_for
import geopandas as gpd
import folium
from matplotlib import pyplot as plt
import numpy as np
import os
from utils import generate_plots, get_monitoring_data
from datetime import datetime

app = Flask(__name__)

# 读取并转换 Shapefile
shapefile_path = "data/WatercourseLink.shp"
gdf = gpd.read_file(shapefile_path).to_crs(epsg=4326)

# 过滤 River Thames 数据
riverline = gdf[gdf["name1"] == "River Lee"]
if riverline.empty:
    raise ValueError("未找到 River Thames 数据")

# 提取河流坐标
river_segments = []
for geom in riverline.geometry:
    if geom.geom_type == "LineString":
        river_segments.append([(lat, lon) for lon, lat, *_ in geom.coords])
    elif geom.geom_type == "MultiLineString":
        river_segments.extend([[(lat, lon) for lon, lat, *_ in line.coords] for line in geom.geoms])

# 计算河流中心
all_coords = [p for segment in river_segments for p in segment]
#center_lat, center_lon = np.mean([p[0] for p in all_coords]), np.mean([p[1] for p in all_coords])

def convert_datetime(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()  # 转换为字符串 "2025-03-22T15:27:37"
    raise TypeError("Type not serializable")

@app.route("/")
def index():
    monitoring_data = get_monitoring_data()
    generate_plots(monitoring_data, "plot")
    return render_template("index.html")

def plot():
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2, 3], [10, 20, 25, 30])  # 示例数据

    # 保存为图片
    img = io.BytesIO()
    fig.savefig(img, format="png")
    img.seek(0)
    img_base64 = base64.b64encode(img.getvalue()).decode()
    
    return f'<img src="data:image/png;base64,{img_base64}"/>'

@app.route("/map")
def generate_map():
    m = folium.Map(location=[51.55, -0.025], zoom_start=12, tiles="CartoDB positron")

    # 绘制 River Thames
    for segment in river_segments:
        folium.PolyLine(segment, color="green", weight=3, opacity=0.8).add_to(m)

    # 获取监测点数据
    monitoring_points = get_monitoring_data()

    # 生成地图上的监测点
    for i, point in enumerate(monitoring_points):
        latest_time = sorted(point["data"].keys())[-1]
        latest_data = point["data"][latest_time]
        popup_html = f"""
        <b>监测点 {i+1}</b><br>
        <b>pH:</b> {latest_data["pH"]:.2f} <br>
        <b>Turbidity:</b> {latest_data["Turbidity"]:.2f} NTU <br>
        <b>DO2:</b> {latest_data["DO2"]:.2f} mg/L <br>
        <b>Conductivity:</b> {latest_data["Conductivity"]:.2f} µS/cm <br>
        <b>E.coli:</b> {latest_data["Ecoli"]:.2f} CFU/100mL <br>
        <a href='/plots/{i+1}'>View Detailed Data</a>
        """

        folium.CircleMarker(
            location=point["location"],
            radius=8,
            color="blue",
            fill=True,
            fill_color="blue",
            fill_opacity=0.6,
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(m)

    return m._repr_html_()

@app.route("/plots/<int:point_id>")
def plot_page(point_id):
    monitoring_data = get_monitoring_data()
    time_steps = list(monitoring_data[0]["data"].keys()) if monitoring_data else []
    for point in monitoring_data:
        if point["point_id"] == point_id:
            return render_template(
                "plots.html",
                point_id=point_id,
                data=point["data"],
                time_steps=time_steps,
                date=None
            )
    return jsonify({"error": "Monitoring point not found"}), 404

@app.route("/plots/<int:point_id>/<string:date>")
def plot_page_with_date(point_id, date):
    if date == "null":  # Handle 'null' as None
        date = None

    try:
        monitoring_data = get_monitoring_data(date)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    time_steps = list(monitoring_data[0]["data"].keys()) if monitoring_data else []
    for point in monitoring_data:
        if point["point_id"] == point_id:
            return render_template(
                "plots.html",
                point_id=point_id,
                data=point["data"],
                time_steps=time_steps,
                date=date
            )
    return jsonify({"error": "Monitoring point not found"}), 404

@app.route("/static/plots/<path:filename>")
def serve_plots(filename):
    return send_from_directory("static/plots", filename)

@app.route("/api/monitoring/<int:point_id>")
def get_monitoring_point(point_id):
    monitoring_data = get_monitoring_data()
    for point in monitoring_data:
        if point["point_id"] == point_id:
            image_url = url_for('serve_plots', filename=f'plot_{point_id}.png')  # 获取图像 URL
            point["image_url"] = image_url  # 在数据中添加图像 URL
            return jsonify(point)
    return jsonify({"error": "Monitoring point not found"}), 404

@app.route("/api/monitoring")
def get_all_monitoring():
    monitoring_data = get_monitoring_data()
    time_steps = [t for t in monitoring_data[0]["data"].keys()] if monitoring_data else []
    return jsonify({"monitoring_data": monitoring_data, "time_steps": time_steps})

@app.route("/api/monitoring/<int:point_id>/<string:time>")
def get_monitoring_point_at_time(point_id, time):
    monitoring_data = get_monitoring_data()
    for point in monitoring_data:
        if point["point_id"] == point_id:
            if time in point["data"]:
                return jsonify({"point_id": point_id, "location": point["location"], "data": point["data"][time]})
    return jsonify({"error": "Data not found"}), 404

@app.route("/api/monitoring/<int:point_id>/<string:time>/<string:date>")
def get_monitoring_point_at_time_and_date(point_id, time, date):
    monitoring_data = get_monitoring_data(date)
    for point in monitoring_data:
        if point["point_id"] == point_id:
            if time in point["data"]:
                return jsonify({"point_id": point_id, "location": point["location"], "data": point["data"][time]})
    return jsonify({"error": "Data not found"}), 404

@app.route("/api/map")
def get_riverline():
    return jsonify(river_segments)

@app.route("/history/<string:date>")
def history(date):
    try:
        monitoring_data = get_monitoring_data(date)
    except ValueError as e:
        return render_template("history.html", date=date, data=[], error=str(e))
    return render_template("history.html", date=date, data=monitoring_data, error=None)

if __name__ == "__main__":
    app.run(debug=True)