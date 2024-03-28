from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from os.path import exists
from typing import Any

import discord.errors
from discord import TextChannel, Message, Embed, Bot


class Tag(Enum):
	NORMAL = 0
	MEDIUM = 1
	BAD = 2
	FAR = 3
	EXPENSIVE = 4


class ModificationMode(Enum):
	ADD = 0
	REMOVE = 1


class Listing:
	def __init__(self, listing_id: int, tag: Tag = Tag.NORMAL):
		self.id: int = listing_id
		self.tags: list[Tag] = [tag]
		self.message: Message | None = None
		self.address: str | None = None
		self.tour_time: datetime | None = None
	
	def __eq__(self, other) -> bool:
		if isinstance(other, Listing):
			return self.id == other.id
		return False
	
	def __repr__(self) -> str:
		return f"Listing[id={self.id}, tags={self.tags}, message_id={self.message.id}]"
	
	def __str__(self) -> str:
		return f"Listing ({self.id})"
	
	@property
	def url(self) -> str:
		return f"https://www.immobilienscout24.de/expose/{self.id}"
	
	def build_embed(self) -> Embed:
		embed = Embed(
			title=self.url,
			description=",".join([tag.name for tag in self.tags])
		)
		
		if self.tour_time:
			embed.add_field(name="Viewing time", value=self.tour_time.isoformat())
		
		return embed
	
	async def update_message(self) -> None:
		await self.message.edit(embed=self.build_embed())
		self.save_all_listings()
	
	async def move_to_channel(self, channel: TextChannel) -> None:
		await self.message.delete()
		new_message: Message = await channel.send(embed=self.build_embed())
		self.message = new_message
		self.save_all_listings()
	
	async def delete(self) -> None:
		# guild_id need to be saved, as message will be deleted
		guild_id: int = self.message.guild.id
		
		if self.message:
			await self.message.delete()
		LISTINGS[guild_id].remove(self)
		
		if len(LISTINGS[guild_id]) == 0:
			LISTINGS.pop(guild_id)
		
		self.save_all_listings()
	
	async def set_address(self, address: str) -> None:
		self.address = address
		await self.update_message()
	
	@staticmethod
	def get_from_id(guild: int, requested_id: int) -> Listing | None:
		if guild not in LISTINGS:
			return None
		
		for listing in LISTINGS[guild]:
			if listing.id == requested_id:
				return listing
		return None
	
	@staticmethod
	def get_from_message_id(message_id: int) -> Listing | None:
		for guild_listings in LISTINGS.values():
			for listing in guild_listings:
				if listing.message.id == message_id:
					return listing
		return None
	
	def add_tag(self, tag: Tag) -> None:
		if tag not in self.tags:
			self.tags.append(tag)
	
	def remove_tag(self, tag: Tag) -> None:
		if tag in self.tags:
			self.tags.remove(tag)
	
	async def set_time(self, time: datetime) -> None:
		self.tour_time = time
		await self.update_message()
	
	def serialize(self) -> dict[str, Any]:
		return {
			"id": self.id,
			"tags": [tag.name for tag in self.tags],
			"message": self.message.id,
			"channel": self.message.channel.id,
			"address": self.address,
			"tour_time": self.tour_time.isoformat() if self.tour_time else None,
		}
	
	@classmethod
	async def deserialize(cls, bot: Bot, data: dict[str, Any]) -> Listing | None:
		try:
			listing = cls(data["id"])
			channel = await bot.fetch_channel(data["channel"])
			listing.message = await channel.fetch_message(data["message"])
			listing.address = data["address"]
			listing.tags = [Tag[name] for name in data["tags"]]
			
			# special handling because of datetime parsing
			if data["tour_time"]:
				listing.tour_time = datetime.fromisoformat(data["tour_time"])
			
			await listing.update_message()
			
			return listing
		except discord.errors.DiscordException:
			return None
	
	_SAVE_FILE: str = "listings.json"
	
	@staticmethod
	def save_all_listings() -> None:
		listings: dict[int, list[dict[str, Any]]] = {}
		for guild_id in LISTINGS:
			listings[guild_id] = [listing.serialize() for listing in LISTINGS[guild_id]]
		
		with open(Listing._SAVE_FILE, "w") as file:
			json.dump(listings, file, indent=4)
	
	@classmethod
	async def load_all_listings(cls, bot: Bot) -> None:
		if not exists(cls._SAVE_FILE):
			print("file does not exist, nothing to load")
			return
		
		with open(cls._SAVE_FILE, "r") as file:
			full_data = json.load(file)
		
		for guild_id in full_data:
			gid = int(guild_id)
			for listing_data in full_data[guild_id]:
				if listing := await cls.deserialize(bot, listing_data):
					if gid in LISTINGS:
						LISTINGS[gid].append(listing)
					else:
						LISTINGS[gid] = [listing]
		
		# messages may have been deleted, update accordingly
		cls.save_all_listings()
		
		print(f"loaded listings for {len(LISTINGS)} guilds ({[len(listings) for listings in LISTINGS.values()]})")


@dataclass
class Channels:
	new: TextChannel
	awaiting_answer: TextChannel
	awaiting_tour: TextChannel
	denied: TextChannel
	accepted: TextChannel


CHANNELS: dict[int, Channels] = {}
LISTINGS: dict[int, list[Listing]] = {}
