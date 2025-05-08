# core_sdk/frontend/utils.py
# Хелперы, которые могут понадобиться (примеры)
from typing import Any, Type, Optional, List, Union, get_origin, get_args
from pydantic import BaseModel
from sqlmodel import SQLModel
from enum import Enum
import inspect

# Пример хелпера для извлечения базового типа
def get_base_type(annotation: Any) -> Type:
    """Извлекает базовый тип, убирая Optional, Union и т.д."""
    origin = get_origin(annotation)
    if origin is Union or str(origin) == 'typing.Union': # Python < 3.10
        args = get_args(annotation)
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return get_base_type(non_none_args[0]) # Рекурсивно для вложенных Optional[Union[...]]
        else:
            # Возвращаем Union или первый тип, если много вариантов
            return annotation
    elif origin is Optional or str(origin) == 'typing.Optional': # Python < 3.10
         args = get_args(annotation)
         return get_base_type(args[0]) if args else Any
    elif origin is list or origin is List:
        return list # Возвращаем сам тип list
    # Добавить другие обертки, если нужно (напр., Annotated)
    return annotation if inspect.isclass(annotation) else type(annotation)

def is_list_type(annotation: Any) -> bool:
    """Проверяет, является ли аннотация списком."""
    origin = get_origin(annotation)
    return origin is list or origin is List

def get_list_item_type(annotation: Any) -> Optional[Type]:
    """Извлекает тип элемента списка."""
    if is_list_type(annotation):
        args = get_args(annotation)
        if args:
            return get_base_type(args[0]) # Возвращаем базовый тип элемента
    return None

def is_relation(annotation: Any) -> bool:
    """Проверяет, является ли тип моделью Pydantic/SQLModel (потенциальная связь)."""
    base_type = get_base_type(annotation)
    return inspect.isclass(base_type) and (issubclass(base_type, BaseModel) or issubclass(base_type, SQLModel))

def get_relation_model_name(annotation: Any) -> Optional[str]:
    """Пытается извлечь имя связанной модели."""
    base_type = get_base_type(annotation)
    if is_relation(base_type):
        # Пытаемся получить имя из ModelRegistry, если она зарегистрирована
        # Это более надежно, чем просто __name__
        from core_sdk.registry import ModelRegistry # Локальный импорт
        try:
            # Ищем модель по классу (нужен обратный поиск в реестре или итерация)
            for name, info in ModelRegistry._registry.items():
                 if info.model_cls == base_type:
                     return name
        except Exception:
             pass # Если реестр не настроен или модель не найдена
        # Фоллбэк на имя класса
        return base_type.__name__
    return None