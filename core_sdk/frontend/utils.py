# core_sdk/frontend/utils.py
from typing import (
    Any,
    Type,
    Optional as TypingOptional,
    List as TypingList,
    Union,
    get_origin,
    get_args,
    Dict as TypingDict,
)
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import SQLModel
import inspect
import uuid


# --- ИСПРАВЛЕННЫЙ get_base_type ---
def get_base_type(annotation: Any) -> Any:
    """
    Рекурсивно извлекает "базовый" тип из сложных аннотаций типа Optional, Union.
    Для List[T] возвращает саму аннотацию List[T].
    Для Dict[K, V] возвращает саму аннотацию Dict[K, V].
    """
    origin = get_origin(annotation)

    if origin is Union:  # Обрабатываем Union (включая Optional)
        args = get_args(annotation)
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return get_base_type(non_none_args[0])  # Рекурсивно для T из Optional[T]
        elif len(non_none_args) > 1:
            # Для Union[A, B], возвращаем первый не-None тип (или сам Union, если нужно)
            return get_base_type(non_none_args[0])
        else:
            return Any
            # Если это List[...] или Dict[...], возвращаем саму аннотацию (например, typing.List[uuid.UUID])
    # а не только origin (list или dict). Это важно для is_list_type и get_list_item_type.
    elif origin is TypingList or origin is list:
        return annotation  # Возвращаем List[T]
    elif origin is TypingDict or origin is dict:
        return annotation  # Возвращаем Dict[K,V]

    return annotation  # Если нет origin или это не специальный generic


# --- ИСПРАВЛЕННЫЙ is_list_type ---
def is_list_type(annotation: Any) -> bool:
    """
    Проверяет, является ли аннотация списком (List[T]), возможно, обернутым в Optional.
    """
    # Сначала "разворачиваем" Optional/Union до самого типа List[T] или другого типа
    type_to_check_origin = get_base_type(annotation)
    origin_of_final_type = get_origin(type_to_check_origin)
    return origin_of_final_type is TypingList or origin_of_final_type is list


# --- ИСПРАВЛЕННЫЙ get_list_item_type ---
def get_list_item_type(annotation: Any) -> Any:
    """
    Извлекает тип элемента списка, даже если список обернут в Optional.
    Возвращает None, если это не список.
    """
    # Сначала "разворачиваем" Optional/Union до самого типа List[T]
    possible_list_type = get_base_type(annotation)

    if (
        get_origin(possible_list_type) is TypingList
        or get_origin(possible_list_type) is list
    ):
        args = get_args(possible_list_type)  # args для List[T] будет (T,)
        if args:
            # Возвращаем базовый тип элемента списка (например, T из List[T] или из Optional[List[Optional[T]]])
            return get_base_type(args[0])
    return None


# --- is_pydantic_sqlmodel_type (без изменений) ---
def is_pydantic_sqlmodel_type(type_to_check: Any) -> bool:
    if inspect.isclass(type_to_check):
        return issubclass(type_to_check, PydanticBaseModel) or issubclass(
            type_to_check, SQLModel
        )
    return False


# --- is_relation (без изменений, но теперь должен работать лучше) ---
def is_relation(annotation: Any) -> bool:
    base_type_of_annotation = get_base_type(annotation)

    # Проверяем, является ли сам base_type_of_annotation списком
    if (
        get_origin(base_type_of_annotation) is TypingList
        or get_origin(base_type_of_annotation) is list
    ):
        # Если это список, получаем тип его элементов
        item_type = get_list_item_type(
            base_type_of_annotation
        )  # get_list_item_type уже вернет базовый тип элемента
        return is_pydantic_sqlmodel_type(item_type)
    else:
        # Если это не список, проверяем сам тип
        return is_pydantic_sqlmodel_type(base_type_of_annotation)


# --- get_relation_model_name (без изменений, но теперь должен работать лучше) ---
def get_relation_model_name(annotation: Any) -> TypingOptional[str]:
    base_type_of_annotation = get_base_type(annotation)

    type_to_get_name_from = base_type_of_annotation
    # Если базовый тип после "разворачивания" Optional - это List, то берем тип элемента
    if (
        get_origin(base_type_of_annotation) is TypingList
        or get_origin(base_type_of_annotation) is list
    ):
        type_to_get_name_from = get_list_item_type(base_type_of_annotation)

    if is_pydantic_sqlmodel_type(type_to_get_name_from):
        from core_sdk.registry import ModelRegistry

        try:
            for name, info in ModelRegistry._registry.items():
                if (
                    info.model_cls == type_to_get_name_from
                    or info.read_schema_cls == type_to_get_name_from
                ):
                    return name
        except Exception:
            pass
        return type_to_get_name_from.__name__
    return None


# Примеры использования для проверки:
if __name__ == "__main__":

    class MyModel(SQLModel):
        id: int

    class AnotherModel(PydanticBaseModel):
        name: str

    ann1 = TypingOptional[TypingList[uuid.UUID]]
    ann2 = TypingOptional[MyModel]
    ann3 = TypingList[AnotherModel]
    ann4 = uuid.UUID
    ann5 = TypingOptional[TypingList[str]]
    ann6 = TypingList[TypingOptional[MyModel]]

    test_cases = {
        "Optional[List[uuid.UUID]]": ann1,
        "Optional[MyModel]": ann2,
        "List[AnotherModel]": ann3,
        "uuid.UUID": ann4,
        "Optional[List[str]]": ann5,
        "List[Optional[MyModel]]": ann6,
    }

    for desc, ann in test_cases.items():
        print(f"\nAnnotation: {desc} ({ann})")
        print(f"  get_base_type: {get_base_type(ann)}")
        print(f"  is_list_type: {is_list_type(ann)}")
        print(f"  get_list_item_type: {get_list_item_type(ann)}")
        print(f"  is_relation: {is_relation(ann)}")
        print(f"  get_relation_model_name: {get_relation_model_name(ann)}")
