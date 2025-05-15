# core_sdk/tests/filters/test_default_filter.py
import uuid

import pytest
from typing import Optional, List, Union
from uuid import uuid4
from datetime import datetime, timedelta, timezone  # Добавил timezone

from pydantic import ValidationError
from sqlmodel import SQLModel, Field, create_engine, Session as SQLModelSession
from sqlalchemy import select, delete as sqlalchemy_delete  # Импортируем delete

from core_sdk.filters.base import DefaultFilter
from core_sdk.db.base_model import BaseModelWithMeta


# --- Тестовая модель ---
class FilterTestModel(BaseModelWithMeta, table=True):
    __tablename__ = "filter_test_model_sdk_v2"  # Новое имя для чистоты
    name: Optional[str] = Field(default=None)
    value: Optional[int] = Field(default=None)


# --- Тесты ---


def test_default_filter_instantiation_with_constants():
    class MyModelSpecificFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel
            search_model_fields = ["name"]

    try:
        filter_instance = MyModelSpecificFilter()
        assert filter_instance is not None
        filter_instance_with_params = MyModelSpecificFilter(
            id__in=[uuid4(), uuid4()], company_id=uuid4(), search="test"
        )
        assert filter_instance_with_params is not None
        assert len(filter_instance_with_params.id__in) == 2
    except Exception as e:
        pytest.fail(f"Failed to instantiate DefaultFilter with Constants.model: {e}")


def test_default_filter_field_definitions():
    fields = DefaultFilter.model_fields

    assert "id__in" in fields
    # Pydantic v2 может представлять Optional[List[UUID]] немного иначе в аннотации,
    # но суть в том, что это список UUID, возможно None.
    # Проверим, что это Optional и что внутренний тип List[uuid.UUID]
    from typing import get_origin, get_args

    assert (
        get_origin(fields["id__in"].annotation) is Union
        or get_origin(fields["id__in"].annotation) is Optional
    )  # Optional это Union[T, None]
    id_in_args = get_args(fields["id__in"].annotation)
    assert any(
        get_origin(arg) is list and get_args(arg)[0] is uuid.UUID
        for arg in id_in_args
        if arg is not type(None)
    )

    assert fields["id__in"].is_required() is False

    assert "company_id" in fields
    assert fields["company_id"].annotation == Optional[uuid.UUID]
    assert fields["company_id"].json_schema_extra.get("rel") == "company"

    assert "company_id__in" in fields
    assert (
        get_origin(fields["company_id__in"].annotation) is Union
        or get_origin(fields["company_id__in"].annotation) is Optional
    )
    company_id_in_args = get_args(fields["company_id__in"].annotation)
    assert any(
        get_origin(arg) is list and get_args(arg)[0] is uuid.UUID
        for arg in company_id_in_args
        if arg is not type(None)
    )
    assert fields["company_id__in"].json_schema_extra.get("rel") == "company"

    assert "created_at__gte" in fields
    assert fields["created_at__gte"].annotation == Optional[datetime]

    assert "order_by" in fields
    assert fields["order_by"].annotation == Optional[List[str]]

    assert "search" in fields
    assert fields["search"].annotation == Optional[str]


def test_default_filter_validation_accepts_valid_data():
    class MyModelSpecificFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel
            search_model_fields = ["name"]

    valid_data = {
        "id__in": [str(uuid4()), str(uuid4())],
        "company_id": str(uuid4()),
        "created_at__gte": datetime.now().isoformat(),
        "order_by": ["name", "-created_at"],
        "search": "some text",
    }
    try:
        filter_instance = MyModelSpecificFilter(**valid_data)
        assert filter_instance.id__in is not None and len(filter_instance.id__in) == 2
        assert isinstance(filter_instance.id__in[0], uuid.UUID)
        assert isinstance(filter_instance.company_id, uuid.UUID)
        assert isinstance(filter_instance.created_at__gte, datetime)
        assert filter_instance.order_by == ["name", "-created_at"]
        assert filter_instance.search == "some text"
    except ValidationError as e:
        pytest.fail(f"DefaultFilter failed to validate correct data: {e.errors()}")


def test_default_filter_validation_rejects_invalid_data():
    class MyModelSpecificFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel
            search_model_fields = ["name"]

    invalid_data_company_id = {"company_id": "not-a-uuid"}
    with pytest.raises(ValidationError):
        MyModelSpecificFilter(**invalid_data_company_id)

    invalid_data_created_at = {"created_at__gte": "not-a-datetime"}
    with pytest.raises(ValidationError):
        MyModelSpecificFilter(**invalid_data_created_at)

    invalid_data_id_in = {"id__in": ["not-a-uuid", str(uuid4())]}
    with pytest.raises(ValidationError):
        MyModelSpecificFilter(**invalid_data_id_in)


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def sync_session(sync_engine):
    with SQLModelSession(sync_engine) as session:
        # Используем sqlalchemy.delete для очистки таблицы
        stmt = sqlalchemy_delete(FilterTestModel)
        session.execute(stmt)
        session.commit()
        yield session


def test_default_filter_applies_id_in(sync_session: SQLModelSession):
    class MyFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel

    id1, id2, id3 = uuid4(), uuid4(), uuid4()
    # Явно устанавливаем lsn, так как он теперь nullable, но unique (если значение не None)
    sync_session.add_all(
        [
            FilterTestModel(id=id1, name="Item 1", company_id=uuid4(), lsn=1),
            FilterTestModel(id=id2, name="Item 2", company_id=uuid4(), lsn=2),
            FilterTestModel(id=id3, name="Item 3", company_id=uuid4(), lsn=3),
        ]
    )
    sync_session.commit()

    filter_instance = MyFilter(id__in=[id1, id3])
    query = filter_instance.filter(select(FilterTestModel))

    results = sync_session.exec(query).scalars().all()
    assert len(results) == 2
    result_ids = {item.id for item in results}
    assert result_ids == {id1, id3}


def test_default_filter_applies_company_id(sync_session: SQLModelSession):
    class MyFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel

    comp_id1, comp_id2 = uuid4(), uuid4()
    sync_session.add_all(
        [
            FilterTestModel(id=uuid4(), name="C1 Item 1", company_id=comp_id1, lsn=10),
            FilterTestModel(id=uuid4(), name="C2 Item 1", company_id=comp_id2, lsn=11),
            FilterTestModel(id=uuid4(), name="C1 Item 2", company_id=comp_id1, lsn=12),
        ]
    )
    sync_session.commit()

    filter_instance = MyFilter(company_id=comp_id1)
    query = filter_instance.filter(select(FilterTestModel))
    results = sync_session.exec(query).scalars().all()
    assert len(results) == 2
    assert all(item.company_id == comp_id1 for item in results)


def test_default_filter_applies_created_at_gte(sync_session: SQLModelSession):
    class MyFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel

    now = datetime.now(timezone.utc)  # Используем timezone.utc
    item1_time = now - timedelta(days=2)
    item2_time = now - timedelta(days=1)
    item3_time = now

    item1 = FilterTestModel(
        id=uuid4(),
        name="Old",
        company_id=uuid4(),
        created_at=item1_time,
        updated_at=item1_time,
        lsn=20,
    )
    item2 = FilterTestModel(
        id=uuid4(),
        name="Mid",
        company_id=uuid4(),
        created_at=item2_time,
        updated_at=item2_time,
        lsn=21,
    )
    item3 = FilterTestModel(
        id=uuid4(),
        name="New",
        company_id=uuid4(),
        created_at=item3_time,
        updated_at=item3_time,
        lsn=22,
    )
    sync_session.add_all([item1, item2, item3])
    sync_session.commit()

    filter_instance = MyFilter(created_at__gte=(now - timedelta(days=1, hours=1)))
    query = filter_instance.filter(select(FilterTestModel))
    results = sync_session.exec(query).scalars().all()

    result_names = {item.name for item in results}
    assert "Mid" in result_names
    assert "New" in result_names
    assert "Old" not in result_names
    assert len(results) == 2


def test_default_filter_applies_search(sync_session: SQLModelSession):
    class MyFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel
            search_model_fields = ["name"]

    sync_session.add_all(
        [
            FilterTestModel(
                id=uuid4(), name="Alpha Search", company_id=uuid4(), lsn=30
            ),
            FilterTestModel(id=uuid4(), name="Beta Test", company_id=uuid4(), lsn=31),
            FilterTestModel(id=uuid4(), name="Gamma Item", company_id=uuid4(), lsn=32),
        ]
    )
    sync_session.commit()

    filter_instance = MyFilter(search="Alpha")
    query = filter_instance.filter(select(FilterTestModel))
    results = sync_session.exec(query).scalars().all()
    assert len(results) == 1
    result_names = {item.name for item in results}
    assert "Alpha Search" in result_names


def test_default_filter_applies_order_by(sync_session: SQLModelSession):
    class MyFilter(DefaultFilter):
        class Constants(DefaultFilter.Constants):
            model = FilterTestModel

    sync_session.add_all(
        [
            FilterTestModel(id=uuid4(), name="Charlie", company_id=uuid4(), lsn=40),
            FilterTestModel(id=uuid4(), name="Alice", company_id=uuid4(), lsn=41),
            FilterTestModel(id=uuid4(), name="Bob", company_id=uuid4(), lsn=42),
        ]
    )
    sync_session.commit()

    filter_asc = MyFilter(order_by=["name"])
    query_asc = filter_asc.sort(select(FilterTestModel))
    results_asc = sync_session.exec(query_asc).scalars().all()
    assert [item.name for item in results_asc] == ["Alice", "Bob", "Charlie"]

    filter_desc = MyFilter(order_by=["-lsn"])
    query_desc = filter_desc.sort(select(FilterTestModel))
    results_desc = sync_session.exec(query_desc).scalars().all()
    assert [item.lsn for item in results_desc] == [42, 41, 40]
