
from django import template

register = template.Library()

# nested_to_flat
@register.filter
def nested_to_flat(nodes):
    if isinstance(nodes, list):
        yield {'start_nodes': True}
        for node in nodes:
            for i in nested_to_flat(node):
                yield i
        yield {'end_nodes': True}
    else:
        yield {'start_node': True}
        yield {'data': nodes, 'is_data': True}
        yield {'end_node': True}
