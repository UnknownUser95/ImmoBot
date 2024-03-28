import re
from datetime import datetime, time, date, timedelta

from discord import Bot, ApplicationContext, Option, AutocompleteContext, Guild, CategoryChannel, TextChannel, ChannelType, Message, Intents
from discord.ext import tasks
from discord.utils import basic_autocomplete

from immobot.classes import LISTINGS, Tag, CHANNELS, Listing, Channels, ModificationMode

# bot: Bot = Bot(intents=Intents.guild_messages)
intents = Intents.default()
intents.guild_messages = True
bot: Bot = Bot(intents=intents)


# --------------- slash command helpers ---------------


def get_listing_for_message(message: Message) -> Listing | None:
	for listing in LISTINGS[message.guild.id]:
		if listing.message.id == message.id:
			return listing
	return None


async def get_all_listings(context: AutocompleteContext) -> list:
	return [listing.id for listing in LISTINGS[context.interaction.guild.id]] if context.interaction.guild.id in LISTINGS else []


async def get_all_tags(context: AutocompleteContext) -> list:
	return [tag.name for tag in Tag]


async def get_tag_mode(context: AutocompleteContext) -> list:
	# always safe
	listing: Listing = Listing.get_from_id(context.interaction.guild.id, int(context.options["id"]))
	mode: ModificationMode = ModificationMode[context.options["mode"]]
	
	print("mode:", mode)
	
	if mode == ModificationMode.ADD:
		return [tag.name for tag in Tag if tag not in listing.tags]
	elif mode == ModificationMode.REMOVE:
		return [tag.name for tag in listing.tags]


async def create_category_if_not_exists(guild: Guild, name: str) -> CategoryChannel:
	cat: CategoryChannel | None = None
	for category in guild.categories:
		if category.name == name:
			cat = category
	
	if cat is None:
		cat = await guild.create_category(name)
	
	return cat


def find_channel_in_category(category: CategoryChannel, name: str) -> TextChannel | None:
	for channel in category.channels:
		if channel.name == name and channel.type == ChannelType.text:
			return channel
	return None


async def create_channel_if_not_exists(category: CategoryChannel, name: str) -> TextChannel:
	channel: TextChannel = find_channel_in_category(category, name)
	if channel is None:
		return await category.create_text_channel(name)
	return channel


# --------------- bot events ---------------


@bot.event
async def on_ready() -> None:
	guilds: list[Guild] = bot.guilds
	for guild in guilds:
		print(f"creating channels for '{guild.name}'...")
		category: CategoryChannel = await create_category_if_not_exists(guild, "listings")
		
		CHANNELS[guild.id] = Channels(
			await create_channel_if_not_exists(category, "new"),
			await create_channel_if_not_exists(category, "awaiting-answer"),
			await create_channel_if_not_exists(category, "awaiting-tour"),
			await create_channel_if_not_exists(category, "denied"),
			await create_channel_if_not_exists(category, "accepted")
		)
		
		print("done")
	
	print("loading all existing listings. This will take some time.")
	await Listing.load_all_listings(bot)
	
	print("bot is ready!")


# --------------- slash commands ---------------


@bot.slash_command(name="add", description="add listing")
async def add_listing(
		context: ApplicationContext,
		url: str,
		address: Option(str, required=False),
		initial_tag: Option(str, autocomplete=basic_autocomplete(get_all_tags), default=Tag.NORMAL)
) -> None:
	result = re.search(r"https://www.immobilienscout24.de/expose/(\d*)\??.*", url)
	
	# no match         | too many matches           | empty string
	if result is None or len(result.groups()) != 1 or not result.group(1):
		await context.respond("invalid url", ephemeral=True)
		return
	
	listing: Listing = Listing(int(result.group(1)), initial_tag)
	if address:
		listing.address = address
	
	if context.guild.id in LISTINGS:
		LISTINGS[context.guild.id].append(listing)
	else:
		LISTINGS[context.guild.id] = [listing]
	
	listing.message = await CHANNELS[context.guild.id].new.send(embed=listing.build_embed())
	
	Listing.save_all_listings()
	
	await context.respond(f"added listing with ID {listing.id}")


@bot.slash_command(name="remove", description="remove listing")
async def remove_listing(
		context: ApplicationContext,
		id: Option(int, autocomplete=basic_autocomplete(get_all_listings)),
) -> None:
	# always safe
	listing = Listing.get_from_id(context.guild.id, id)
	
	await listing.delete()
	
	await context.respond(id)


@bot.slash_command(name="tag", description="add tag to listing")
async def modify_tags(
		context: ApplicationContext,
		id: Option(int, autocomplete=basic_autocomplete(get_all_listings)),
		mode: Option(str, choices=[mode.name for mode in ModificationMode]),
		tag: Option(str, autocomplete=basic_autocomplete(get_tag_mode))
) -> None:
	listing = Listing.get_from_id(context.guild.id, id)
	mode: ModificationMode = ModificationMode[mode]
	tag: Tag = Tag[tag]
	
	if mode == ModificationMode.ADD:
		listing.add_tag(tag)
		await context.respond(f"added tag {tag.name} to {listing.id}", ephemeral=True)
	elif mode == ModificationMode.REMOVE:
		listing.remove_tag(tag)
		await context.respond(f"removed tag {tag.name} from {listing.id}", ephemeral=True)
	
	await listing.update_message()


@bot.slash_command(name="add-tour-date")
async def add_tour_time(
		context: ApplicationContext,
		id: Option(int, autocomplete=basic_autocomplete(get_all_listings)),
		day: int | None,
		month: int | None,
		year: int | None,
		hour: int | None,
		minute: int | None
):
	listing: Listing = Listing.get_from_id(context.guild.id, id)
	now: datetime = datetime.now()
	tour_time = datetime(
		day=day if day else now.day,
		month=month if month else now.month,
		year=year if year else now.year,
		hour=hour if hour else now.hour,
		minute=minute if minute else now.minute - now.minute % 30
	)
	
	await listing.set_time(tour_time)
	await context.respond(f"time set to {listing.tour_time.isoformat()}", ephemeral=True)


@bot.slash_command(name="add-address")
async def add_address(
		context: ApplicationContext,
		id: Option(int, autocomplete=basic_autocomplete(get_all_listings)),
		address: str | None
):
	listing: Listing = Listing.get_from_id(context.guild.id, id)
	
	if address:
		await listing.set_address(address)
		await context.respond(f"set address on {listing.id} to {address}", ephemeral=True)
	else:
		await listing.set_address(None)
		await context.respond(f"removed address from {listing.id}", ephemeral=True)


@bot.slash_command(name="debug")
async def list_everything(
		context: ApplicationContext
):
	context.respond(LISTINGS, ephemeral=True)
	context.respond(CHANNELS, ephemeral=True)


# --------------- message interaction handler ---------------


async def move_listing_if_exists(context: ApplicationContext, message: Message, target_channel: TextChannel) -> None:
	ref: Listing | None = get_listing_for_message(message)
	
	if ref is None:
		await context.respond("no listing associated with message", ephemeral=True)
		return
	
	await ref.move_to_channel(target_channel)
	await context.respond(f"moved listing {ref.id} to {target_channel.name}", ephemeral=True)


@bot.message_command(name="Request Sent")
async def request_sent_handler(context: ApplicationContext, message: Message) -> None:
	await move_listing_if_exists(context, message, CHANNELS[context.guild.id].awaiting_answer)


@bot.message_command(name="Awaiting Tour")
async def tour_awaiting_handler(context: ApplicationContext, message: Message) -> None:
	await move_listing_if_exists(context, message, CHANNELS[context.guild.id].awaiting_tour)


@bot.message_command(name="Application Denied")
async def tour_awaiting_handler(context: ApplicationContext, message: Message) -> None:
	await move_listing_if_exists(context, message, CHANNELS[context.guild.id].denied)


@bot.message_command(name="Application Accepted")
async def tour_awaiting_handler(context: ApplicationContext, message: Message) -> None:
	await move_listing_if_exists(context, message, CHANNELS[context.guild.id].accepted)


# --------------- tasks ---------------


# UTC time!
@tasks.loop(time=time(hour=20))
async def reminder():
	tomorrow: date = datetime.now().date() + timedelta(days=1)
	
	for guild in bot.guilds:
		tours_next_day: list[Listing] = []
		
		for listing in LISTINGS[guild.id]:
			if listing.tour_time.date() == tomorrow:
				tours_next_day.append(listing)
		
		if len(tours_next_day) > 0:
			await CHANNELS[guild.id].awaiting_tour.send(f"@everyone there are tours tomorrow: {', '.join([tour.url for tour in tours_next_day])}")
reminder.start()
