from zeromail import ZeroMail
from message import Message
from config import zeronet_directory
import zeronet
from pop3.util import CommandError
import email, time, datetime, json, re, base64

class Mailbox(object):
	def __init__(self, user, password):
		if user == "local" and password == "local":
			self.zeroid, self.pub, self.priv = zeronet.guess_private_key(zeronet_directory)
			if self.zeroid is None:
				raise CommandError("Failed to access users.json")
			elif self.pub is None or self.priv is None:
				raise CommandError("Could not find user passwords")
		elif user == "local":
			self.zeroid, self.pub, _ = zeronet.guess_private_key(zeronet_directory)
			if self.zeroid is None:
				raise CommandError("Failed to access users.json")
			elif self.pub is None:
				raise CommandError("Could not find user passwords")
		elif password == "local":
			try:
				self.zeroid = user[:user.index(":")]
				self.pub = user[user.index(":")+1:]
			except ValueError:
				raise CommandError("Incorrect login")

			zeroid, _, self.priv = zeronet.guess_private_key(zeronet_directory)
			if zeroid is None:
				raise CommandError("Failed to access users.json")
			elif self.priv is None:
				raise CommandError("Could not find user passwords")
		else:
			try:
				self.zeroid = user[:user.index(":")]
				self.pub = user[user.index(":")+1:]
			except ValueError:
				raise CommandError("Incorrect login")
			self.priv = password

		self.zeromail = ZeroMail(zeronet_directory, zeroid=self.zeroid, pub=self.pub, priv=self.priv)
		self.message_ids = dict()

	def load_messages(self):
		secrets = self.zeromail.update_secrets()
		messages = self.zeromail.update_messages(secrets)
		messages = {date: Message(int(date), data) for date, data in messages.iteritems()}
		return messages

	def messageCount(self):
		return len(self.load_messages())
	def __len__(self):
		return sum([len(message) for message in self.load_messages()])

	def getMessageIds(self):
		self.message_ids = dict(enumerate(self.load_messages().keys()))
		return self.message_ids.keys()
	def expandMessageId(self, message):
		self.load_messages()
		try:
			return self.message_ids[int(message)]
		except KeyError:
			return None

	def __contains__(self, message):
		messages = self.load_messages()
		message_id = self.expandMessageId(message)
		return message_id is not None and message_id in messages
	def __getitem__(self, message):
		messages = self.load_messages()
		return messages[self.expandMessageId(message)]

	def pop(self, message):
		secrets = self.zeromail.update_secrets()
		self.zeromail.remove_message(secrets, self.expandMessageId(message))

	def acceptsRecipient(self, address):
		try:
			self.zeromail.zeroid_to_address(address[:address.rindex("@")])
			return True
		except TypeError:
			return False

	def send(self, from_, to, data):
		message = email.message_from_string(data)

		subject = self.parse_subject(message["Subject"])
		timestamp = time.mktime(datetime.datetime(*email.utils.parsedate(message["Date"])[:6]).timetuple())

		content = self.walk(message)
		if content is None:
			content = "<no data>"

		messages = []
		for i, address in enumerate(to):
			address = address[:address.rindex("@")]
			sign = i == len(to) - 1
			self.zeromail.send(subject=subject, body=content, to=address, date=timestamp * 1000, sign=sign)

	def walk(self, message):
		content_type = message.get_content_type()
		if content_type == "multipart/alternative":
			# Try to find text/html
			for part in message.get_payload():
				if part.get_content_type() == "text/html":
					return self.walk(part)

			# Try to find text/plain
			for part in message.get_payload():
				if part.get_content_type() == "text/plain":
					return self.walk(part)

			return None
		elif message.is_multipart():
			res = []

			for part in message.get_payload():
				part = self.walk(part)
				if part is not None:
					res.append(part)

			return "\n\n".join(content)
		elif content_type == "text/html":
			# Only text/html
			return self.html_to_markdown(self.parse_message(message))
		elif content_type == "text/plain":
			# Only text/plain
			return self.parse_message(message)
		else:
			return None

	def parse_message(self, message):
		content = message.get_payload(decode=True)
		content = content.replace("\r\n", "\n")
		return content

	def parse_subject(self, subject):
		if subject.startswith("=?") and subject.endswith("?="):
			subject = subject[2:-2]

			charset = subject[:subject.index("?")]
			subject = subject[subject.index("?")+1:]

			encoding = subject[:subject.index("?")]
			subject = subject[subject.index("?")+1:]

			if encoding == "B":
				return base64.b64decode(subject).decode(charset)
			elif encoding == "Q":
				return self.parse_quoted_printable(subject).decode(charset)
			else:
				return "<could not decode subject>"

		return subject
	def parse_quoted_printable(self, subject):
		res = ""
		pos = 0
		while pos < len(subject):
			if subject[pos] == "=":
				char = subject[pos+1:pos+3]
				char = int(char, 16)
				char = chr(char)
				res += char
				pos += 2
			else:
				res += subject[pos]
				pos += 1
		return res

	def html_to_markdown(self, html):
		# Remove spaces
		html = re.sub(r" {2,}", " ", html)

		# Generate random constant
		import random
		constant = "CONSTANTBEGINS" + str(random.randint(0, 100000)) + "HOPETHISISUNIQUE"

		# HTML to markdown
		import html2text
		markdown = html2text.html2text(html)

		# Delete single \n
		markdown = markdown.replace("\n\n", constant)
		markdown = markdown.replace("\n", " ")
		markdown = markdown.replace(constant, "\n\n")

		return markdown