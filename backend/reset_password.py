import asyncio
import getpass

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password
from app.database.session import Database
from app.models.user import User


async def main():
    settings = get_settings()
    database = Database.from_settings(settings)

    try:
        email = input("Registered email: ").strip().lower()
        password = getpass.getpass("Enter new password: ")
        confirm = getpass.getpass("Confirm new password: ")

        if password != confirm:
            print("Passwords do not match.")
            return

        if len(password) < 8 or len(password) > 128:
            print("Password must contain 8 to 128 characters.")
            return

        async with database.session_factory() as session:
            result = await session.execute(
                select(User).where(func.lower(User.email) == email)
            )
            user = result.scalar_one_or_none()

            if user is None:
                print("No account found for that email.")
                return

            confirmation = input(
                f"Reset password for {user.email}? (yes/no): "
            ).strip().lower()

            if confirmation != "yes":
                print("Password reset cancelled.")
                return

            user.hashed_password = hash_password(password)
            await session.commit()

            print("Password updated successfully.")

    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())