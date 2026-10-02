import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_database_connection(session):
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1
