"""
llmwikify 与 Django 集成示例

演示如何将 llmwikify 作为 Django 项目的知识库后端。

注意：此为示例代码，需要根据实际项目调整。
"""

print("=" * 60)
print("llmwikify 与 Django 集成示例")
print("=" * 60)

django_example = '''
# ========== settings.py ==========
# 配置 Wiki 根目录
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LLMWIKIFY_ROOT = BASE_DIR / "data" / "wiki"
LLMWIKIFY_CONFIG = {
    # 可选配置
    "mcp": {
        "name": "django-wiki",
    }
}


# ========== wiki.py (应用模块) ==========
\"""Wiki 单例管理。\"""

import threading
from pathlib import Path
from django.conf import settings

from llmwikify import Wiki, create_wiki


_wiki_instance = None
_wiki_lock = threading.Lock()


def get_wiki() -> Wiki:
    """获取 Wiki 单例实例。"""
    global _wiki_instance

    if _wiki_instance is None:
        with _wiki_lock:
            if _wiki_instance is None:
                wiki_path = Path(settings.LLMWIKIFY_ROOT)
                _wiki_instance = create_wiki(
                    wiki_path,
                    config=getattr(settings, "LLMWIKIFY_CONFIG", None)
                )
                # 确保目录初始化
                if not (wiki_path / "wiki").exists():
                    _wiki_instance.init()

    return _wiki_instance


# ========== views.py ==========
\"""Wiki 视图。\"""

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from .wiki import get_wiki


@require_GET
def wiki_search(request):
    \"\"\"Wiki 搜索 API。\"\"\"
    query = request.GET.get("q", "")
    limit = int(request.GET.get("limit", 10))
    backend = request.GET.get("backend", "fts5")

    wiki = get_wiki()
    results = wiki.search(query, limit=limit, backend=backend)

    return JsonResponse({
        "query": query,
        "count": len(results),
        "results": results,
    })


@require_GET
def wiki_page(request, page_name: str):
    \"\"\"读取 Wiki 页面。\"\"\"
    wiki = get_wiki()
    content = wiki.read_page(page_name)

    if isinstance(content, dict) and content.get("error"):
        return JsonResponse(content, status=404)

    return JsonResponse({
        "page_name": page_name,
        "content": content,
    })


@csrf_exempt
@require_POST
def wiki_write_page(request):
    \"\"\"写入 Wiki 页面。\"\"\"
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    page_name = data.get("page_name")
    content = data.get("content")

    if not page_name or not content:
        return JsonResponse(
            {"error": "page_name and content are required"},
            status=400
        )

    wiki = get_wiki()
    result = wiki.write_page(page_name, content)

    return JsonResponse({
        "status": "success",
        "page_name": page_name,
        "result": result,
    })


# ========== urls.py ==========
\"""Wiki URL 配置。\"""

from django.urls import path
from . import views

urlpatterns = [
    path("wiki/search/", views.wiki_search, name="wiki_search"),
    path("wiki/page/<path:page_name>/", views.wiki_page, name="wiki_page"),
    path("wiki/page/", views.wiki_write_page, name="wiki_write_page"),
]


# ========== signals.py ==========
\"""信号处理。\"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

from .wiki import get_wiki


@receiver(post_save, sender=User)
def log_user_creation(sender, instance, created, **kwargs):
    \"\"\"记录用户创建到 Wiki 日志。\"""
    if created:
        wiki = get_wiki()
        wiki.append_log(
            "user_created",
            f"User {instance.username} ({instance.email}) created account"
        )
'''

print(django_example)
print("\n" + "=" * 60)
print("✓ Django 集成示例完成！")
print("=" * 60)
