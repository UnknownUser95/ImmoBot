import os

import dotenv

dotenv.load_dotenv()

TOKEN: str = os.getenv("DISCORD_TOKEN")
