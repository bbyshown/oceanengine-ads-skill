"""Bounded CLI output. Persistent plans and receipts retain replay data."""
import json


def visible(value, full=False, depth=0):
    if isinstance(value, dict):
        result = {}
        items = list(value.items())
        selected = items if full else items[:30]
        for key, item in selected:
            if key == 'base64':
                if isinstance(item, str):
                    result['upload_bytes'] = len(item) * 3 // 4 - len(item) + len(item.rstrip('='))
                result['upload_body_omitted'] = True
            elif not full and depth >= 5 and isinstance(item, (dict, list)):
                result[key] = {'items': len(item), 'details_in_file': True}
            else:
                result[key] = visible(item, full, depth + 1)
        if len(selected) != len(items):
            result['omitted_fields'] = len(items) - len(selected)
        return result
    if isinstance(value, list):
        items = value if full else value[:10]
        result = [visible(item, full, depth + 1) for item in items]
        if len(items) != len(value):
            result.append({'omitted_items': len(value) - len(items), 'total_items': len(value)})
        return result
    if isinstance(value, str) and not full and len(value) > 500:
        return value[:500] + '… [truncated]'
    return value


def outcome(receipt):
    results = []
    for index, step in enumerate(receipt.get('steps', [])):
        response = step.get('response') or {}
        result = response.get('result') or {}
        data = result.get('data') or {}
        row = {'step': index + 1, 'job_id': step.get('job_id'),
               'status': step.get('status'), 'verified': step.get('verified', False)}
        for source in (result, data):
            for key in ('code', 'message', 'error', 'creation_id', 'project_id', 'promotion_id',
                        'image_id', 'video_id', 'audio_id', 'carousel_id', 'change_id'):
                if key in source:
                    row[key] = source[key]
        for key, fields in (
            ('project', ('project_id', 'name', 'opt_status', 'status')),
            ('ad', ('promotion_id', 'project_id', 'promotion_name', 'name', 'opt_status', 'status', 'status_second')),
            ('audio_info', ('audio_id', 'material_id')),
            ('carousel', ('carousel_id',)),
        ):
            source = data.get(key) or {}
            if isinstance(source, dict):
                row.update({field: source[field] for field in fields if field in source})
        stages = data.get('stages') or {}
        for kind, field in (('project', 'project_id'), ('promotion', 'promotion_id')):
            stage = stages.get(kind) or {}
            if field in stage:
                row.setdefault(field, stage[field])
        results.append(row)
    return {'run_id': receipt.get('run_id'), 'account_id': receipt.get('account_id'),
            'status': receipt.get('status'), 'steps': len(receipt.get('steps', [])), 'results': results}


def print_json(value, full=False):
    print(json.dumps(visible(value, full), ensure_ascii=False, indent=2))
