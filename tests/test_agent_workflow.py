"""Checks for agent workflow documentation required by task 08."""

from __future__ import annotations

from pathlib import Path


REQUIRED_MODULE_DOC_SECTIONS = [
    "## Назначение",
    "## Публичные классы и функции",
    "## Используемые настройки",
    "## Взаимодействие с другими модулями",
    "## Обработка ошибок",
    "## Тестирование",
    "## Пример использования",
]

MODULE_DOCS = [
    "schemas.md",
    "config.md",
    "database.md",
    "ai.md",
    "telegram.md",
    "service.md",
    "scheduler.md",
    "main.md",
    "tests.md",
]


def test_agents_file_documents_shared_workflow_rules() -> None:
    agents_doc = Path("AGENTS.md")

    assert agents_doc.exists()
    content = agents_doc.read_text(encoding="utf-8")

    assert "Прочитать `doc`" in content
    assert "Прочитать `docs/ARCHITECTURE.md`" in content
    assert "Общие сущности импортировать из `app.schemas`" in content
    assert "`app/service.py` должен оставаться единственным местом бизнес-процесса публикации" in content
    assert "Не делать реальные API-вызовы в unit-тестах" in content


def test_each_module_doc_uses_required_result_structure() -> None:
    docs_dir = Path("docs/modules")

    for doc_name in MODULE_DOCS:
        module_doc = docs_dir / doc_name
        assert module_doc.exists(), f"Missing module documentation: {module_doc}"
        content = module_doc.read_text(encoding="utf-8")

        assert content.startswith("# Модуль"), f"{module_doc} must start with a module heading"
        for section in REQUIRED_MODULE_DOC_SECTIONS:
            assert section in content, f"{module_doc} is missing section {section!r}"
