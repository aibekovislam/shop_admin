import json

from django import forms


class KeyValueJSONWidget(forms.Widget):
    template_name = "core/admin/key_value_json_widget.html"

    def format_value(self, value):
        if value in (None, ""):
            return "{}"
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def value_from_datadict(self, data, files, name):
        keys = self.get_list(data, f"{name}_key")
        values = self.get_list(data, f"{name}_value")
        result = {}

        for key, value in zip(keys, values, strict=False):
            key = key.strip()
            value = value.strip()
            if not key and not value:
                continue
            result[key] = value

        return json.dumps(result, ensure_ascii=False)

    def get_list(self, data, key):
        if hasattr(data, "getlist"):
            return data.getlist(key)
        value = data.get(key, [])
        return value if isinstance(value, list) else [value]

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        parsed_value = self.parse_value(value)
        context["widget"]["json_value"] = json.dumps(parsed_value, ensure_ascii=False)
        context["widget"]["pairs"] = list(parsed_value.items()) or [("", "")]
        return context

    def parse_value(self, value):
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return value
        try:
            parsed_value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed_value if isinstance(parsed_value, dict) else {}
