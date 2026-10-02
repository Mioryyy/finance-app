import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_connection(db_test):
    result = await db_test.execute(text("SELECT 1"))

    assert result.scalar() == 1
