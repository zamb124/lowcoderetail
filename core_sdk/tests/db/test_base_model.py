# core_sdk/tests/db/test_base_model.py
import pytest
import uuid
from datetime import datetime, timezone
from typing import Optional
import asyncio

from sqlmodel import Field, select
from sqlalchemy.ext.asyncio import AsyncSession

from core_sdk.db.base_model import BaseModelWithMeta

pytestmark = pytest.mark.asyncio


class ConcreteTestModelOne(BaseModelWithMeta, table=True):
    __tablename__ = "concrete_test_model_one_v4"  # Новое имя для чистоты
    name: Optional[str] = Field(default=None)


class ConcreteTestModelTwo(BaseModelWithMeta, table=True):
    __tablename__ = "concrete_test_model_two_v4"  # Новое имя
    description: Optional[str] = Field(default=None)


async def test_create_instance_defaults_and_values(db_session: AsyncSession):
    company_uuid = uuid.uuid4()
    new_id = uuid.uuid4()
    test_lsn = 1

    item = ConcreteTestModelOne(
        id=new_id, name="Test Item", lsn=test_lsn, company_id=company_uuid
    )

    # ID генерируется default_factory, LSN мы передаем
    assert item.id == new_id
    assert item.lsn == test_lsn
    assert item.vars == {}
    assert item.created_at is None
    assert item.updated_at is None
    assert item.company_id == company_uuid

    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.id == new_id
    assert item.name == "Test Item"
    assert item.vars == {}
    assert isinstance(item.created_at, datetime)
    assert isinstance(item.updated_at, datetime)
    if item.created_at.tzinfo is not None:
        assert item.created_at.tzinfo is timezone.utc
    if item.updated_at.tzinfo is not None:
        assert item.updated_at.tzinfo is timezone.utc
    assert item.company_id == company_uuid
    assert item.lsn == test_lsn


async def test_update_instance_modifies_updated_at(db_session: AsyncSession):
    item_id = uuid.uuid4()
    item_lsn = 10
    item = ConcreteTestModelOne(
        id=item_id, name="Initial", company_id=uuid.uuid4(), lsn=item_lsn
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    original_updated_at = item.updated_at
    assert original_updated_at is not None

    await asyncio.sleep(0.01)

    item.name = "Updated Name"
    await db_session.commit()
    await db_session.refresh(item)

    assert item.updated_at is not None
    assert item.lsn == item_lsn


async def test_vars_field_stores_json_data(db_session: AsyncSession):
    custom_data = {"key1": "value1", "nested": {"num": 123, "bool": True}}
    item_id = uuid.uuid4()
    item_lsn = 20
    item = ConcreteTestModelOne(
        id=item_id,
        name="Vars Test",
        company_id=uuid.uuid4(),
        vars=custom_data,
        lsn=item_lsn,
    )

    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.vars == custom_data

    fetched_item = await db_session.get(ConcreteTestModelOne, item.id)
    assert fetched_item is not None
    assert fetched_item.vars == custom_data
    assert fetched_item.lsn == item_lsn


async def test_company_id_storage(db_session: AsyncSession):
    company_id_val = uuid.uuid4()
    item_id = uuid.uuid4()
    item_lsn = 40
    item = ConcreteTestModelOne(
        id=item_id, name="Company ID Test", company_id=company_id_val, lsn=item_lsn
    )

    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    assert item.company_id == company_id_val

    fetched_item = await db_session.get(ConcreteTestModelOne, item.id)
    assert fetched_item is not None
    assert fetched_item.company_id == company_id_val
    assert fetched_item.lsn == item_lsn


async def test_querying_by_base_model_fields(db_session: AsyncSession):
    company1 = uuid.uuid4()
    company2 = uuid.uuid4()

    item1_id, item1_lsn = uuid.uuid4(), 200
    item2_id, item2_lsn = uuid.uuid4(), 201
    item3_id, item3_lsn = uuid.uuid4(), 202

    item1 = ConcreteTestModelOne(
        id=item1_id,
        name="Query Item 1",
        company_id=company1,
        vars={"tag": "A"},
        lsn=item1_lsn,
    )
    item2 = ConcreteTestModelOne(
        id=item2_id,
        name="Query Item 2",
        company_id=company2,
        vars={"tag": "B"},
        lsn=item2_lsn,
    )
    item3 = ConcreteTestModelOne(
        id=item3_id,
        name="Query Item 3",
        company_id=company1,
        vars={"tag": "C"},
        lsn=item3_lsn,
    )

    db_session.add_all([item1, item2, item3])
    await db_session.commit()

    # Используем session.execute для SQLAlchemy Core / ORM запросов
    results_comp1 = await db_session.execute(
        select(ConcreteTestModelOne).where(ConcreteTestModelOne.company_id == company1)
    )
    items_comp1 = results_comp1.scalars().all()
    assert len(items_comp1) == 2
    assert {item.name for item in items_comp1} == {"Query Item 1", "Query Item 3"}

    # await db_session.refresh(item1) # Не обязательно, если id уже есть
    result_by_id = await db_session.execute(
        select(ConcreteTestModelOne).where(ConcreteTestModelOne.id == item1.id)
    )
    item_by_id = result_by_id.scalar_one_or_none()  # scalar_one_or_none()
    assert item_by_id is not None
    assert item_by_id.name == "Query Item 1"

    result_lsn = await db_session.execute(
        select(ConcreteTestModelOne).where(ConcreteTestModelOne.lsn == item2_lsn)
    )
    item_lsn_res = result_lsn.scalar_one_or_none()  # scalar_one_or_none()
    assert item_lsn_res is not None
    assert item_lsn_res.name == "Query Item 2"
