"""
DEPRECATED — 保留作为 Flask 集成参考。
新端到端剧本见 ../01_personal_reading_notes/（Python Wiki API 用法）。

llmwikify 与 Flask 集成示例

演示如何将 llmwikify 作为 Flask 项目的知识库后端。

注意：此为示例代码，需要根据实际项目调整。
"""

print("=" * 60)
print("llmwikify 与 Flask 集成示例")
print("=" * 60)

flask_example = '''
# ========== app.py ==========
\"""Flask Wiki 应用。\"""

from flask import Flask, request, jsonify, render_template
from pathlib import Path

from llmwikify import create_wiki


def create_app():
    \"\"\"创建 Flask 应用。\"""
    app = Flask(__name__)

    # 配置
    app.config["WIKI_ROOT"] = Path("./data/wiki")
    app.config["WIKI_CONFIG"] = {}

    # 初始化 Wiki
    wiki = create_wiki(
        app.config["WIKI_ROOT"],
        config=app.config["WIKI_CONFIG"]
    )

    # 确保目录初始化
    if not (app.config["WIKI_ROOT"] / "wiki").exists():
        wiki.init()

    # 将 wiki 注入请求上下文
    @app.before_request
    def before_request():
        request.wiki = wiki

    # ====== 路由 ======

    @app.route("/")
    def index():
        \"\"\"首页。\"\"\"
        status = wiki.status()
        return render_template("index.html", status=status)

    @app.route("/search")
    def search():
        \"\"\"搜索页面。\"\"\"
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", 10))
        backend = request.args.get("backend", "fts5")

        results = wiki.search(query, limit=limit, backend=backend)
        return render_template("search.html", query=query, results=results)

    @app.route("/api/search")
    def api_search():
        \"\"\"搜索 API。\"\"\"
        query = request.args.get("q", "")
        limit = int(request.args.get("limit", 10))
        backend = request.args.get("backend", "fts5")

        results = wiki.search(query, limit=limit, backend=backend)
        return jsonify({
            "query": query,
            "count": len(results),
            "results": results,
        })

    @app.route("/page/<path:page_name>")
    def read_page(page_name):
        \"\"\"读取页面。\"\"\"
        content = wiki.read_page(page_name)
        if isinstance(content, dict) and content.get("error"):
            return render_template("404.html"), 404
        return render_template("page.html", page_name=page_name, content=content)

    @app.route("/api/page/<path:page_name>", methods=["GET"])
    def api_read_page(page_name):
        \"\"\"读取页面 API。\"""
        content = wiki.read_page(page_name)
        if isinstance(content, dict) and content.get("error"):
            return jsonify(content), 404
        return jsonify({"page_name": page_name, "content": content})

    @app.route("/api/page", methods=["POST"])
    def api_write_page():
        \"\"\"写入页面 API。\"\"\"
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        page_name = data.get("page_name")
        content = data.get("content")

        if not page_name or not content:
            return jsonify({"error": "page_name and content are required"}), 400

        result = wiki.write_page(page_name, content)
        return jsonify({
            "status": "success",
            "page_name": page_name,
            "result": result,
        })

    @app.route("/api/status")
    def api_status():
        \"\"\"知识库状态 API。\"\"\"
        status = wiki.status()
        lint = wiki.lint(format="brief")
        return jsonify({
            "status": status,
            "lint": lint,
        })

    @app.route("/api/lint")
    def api_lint():
        \"\"\"健康检查 API。\"\"\"
        fmt = request.args.get("format", "brief")
        result = wiki.lint(format=fmt)
        return jsonify(result)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)


# ========== requirements.txt ==========
flask>=3.0.0
llmwikify>=0.30.0


# ========== 运行应用 ==========
$ mkdir -p data/wiki
$ python app.py
$ open http://localhost:5000

# ========== 调用 API 示例 ==========
$ curl http://localhost:5000/api/status
$ curl http://localhost:5000/api/search?q=python
$ curl -X POST http://localhost:5000/api/page \\\\
  -H "Content-Type: application/json" \\\\
  -d '{"page_name": "Test", "content": "# Test Page"}'
'''

print(flask_example)
print("\n" + "=" * 60)
print("✓ Flask 集成示例完成！")
print("=" * 60)
