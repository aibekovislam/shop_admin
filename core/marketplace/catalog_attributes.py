"""Resolve catalog specifications against the selected O!Market branches."""

import json
import re
import unicodedata


def normalize(value):
    text = unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")
    text = text.replace("gb", "гб").replace("tb", "тб").replace("usb type-c", "usb-c")
    return re.sub(r"[^\w]+", "", text)


ALIASES = (
    ("Бренд", "Производитель", "Производители"),
    ("Память", "Объем памяти", "Объем встроенной памяти", "Встроенная память"),
    ("Оперативная память", "Объем оперативной памяти", "ОЗУ"),
    ("Процессор", "Чип"),
    ("Разъем", "Интерфейс", "Порт зарядки"),
    ("Матрица экрана", "Тип экрана", "Технология экрана"),
    ("Операционная система", "ОС"),
    ("Камера", "Основная камера"),
)


def label_key(label):
    label = re.sub(r"\s+смартфон(?:ы|ов)?\b", "", str(label), flags=re.I)
    label = re.sub(r",\s*(?:ГБ|дюйм[а-я]*)\s*$", "", label, flags=re.I)
    key = normalize(label)
    for aliases in ALIASES:
        if key in {normalize(alias) for alias in aliases}:
            return normalize(aliases[0])
    return key


def parse_attrs_document(text):
    # Server exports may include a shell prompt and a status line around JSON.
    start = re.search(r"(?m)^\s*[\[{]", text)
    if not start:
        raise ValueError("В файле атрибутов не найден JSON")
    data, _ = json.JSONDecoder().raw_decode(text[start.start():].lstrip())
    if isinstance(data, list):
        return {"16": data}
    if not isinstance(data, dict):
        raise ValueError("Ожидается словарь category_id или список атрибутов")
    return data


def match_attributes(attributes, specs):
    desired = {label_key(label): str(value) for label, value in specs.items() if value not in (None, "")}
    selected = {}
    unresolved = []

    def visit(nodes):
        for attribute in nodes:
            label = attribute.get("create_label") or attribute.get("label") or attribute.get("name") or ""
            key = label_key(label)
            value = desired.get(key)
            if value is None:
                if attribute.get("required") is True or attribute.get("is_required") is True:
                    unresolved.append({"label": label, "reason": "нет подтвержденного значения"})
                continue
            candidates = {normalize(value)}
            if key in {label_key("Память"), label_key("Оперативная память")}:
                candidates.add(normalize(re.sub(r"\s*ГБ$", "", value, flags=re.I)))
            options = attribute.get("values") or attribute.get("options") or []
            found = [option for option in options if normalize(option.get("value") or option.get("name") or "") in candidates]
            if len(found) != 1:
                unresolved.append({"label": label, "value": value, "reason": "значение отсутствует или неоднозначно"})
                continue
            attribute_id = int(attribute.get("id") or attribute.get("attribute_id"))
            option = found[0]
            value_id = int(option.get("id") or option.get("value_id"))
            if attribute_id in selected and selected[attribute_id] != value_id:
                raise ValueError(f"Конфликт значений O!Market attribute_id={attribute_id}")
            selected[attribute_id] = value_id
            visit(option.get("attributes") or [])

    visit(attributes)
    return [{"attribute_id": key, "value_id": value} for key, value in selected.items()], unresolved


def has_brand_dependencies(attributes):
    return any(
        label_key(node.get("label") or node.get("name") or node.get("create_label") or "") == label_key("Бренд")
        and any(option.get("attributes") for option in node.get("values", []))
        for node in attributes
    )
