import os
import sys
import smtplib
import argparse
from bs4 import BeautifulSoup
from requests import get
from sqlalchemy import create_engine, exc, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from email.message import EmailMessage


parser = argparse.ArgumentParser(description='DealScraper')
parser.add_argument(
	'name',
	type=str,
	help='enter a title'
)
parser.add_argument(
	'client_email',
	type=str,
	help='enter an email address'
)
parser.add_argument(
	'-u',
	help='enter each CL url with a -u and single quotes, ex: -u \'http://\' -u \'http://\'',
	dest='urls', 
	default=[],
	action='append' 
)
group = parser.add_mutually_exclusive_group()
group.add_argument('-q','--quiet',action='store_true')
group.add_argument('-v','--verbose',action='store_true')

args = parser.parse_args()

# SETUP LOCAL DATABASE 
Base = declarative_base()

class Posts(Base):
    __tablename__ = "posts"

    timing = Column(String(120), unique=False, nullable=False, primary_key=True)
    title_text = Column(String(120), unique=False, nullable=False)
    link = Column(String(120), unique=False, nullable=False)

class DealScraper:
	def __init__(self, urls, name, client_email):
		# REMOVE SINGLE QUOTES FROM ARGPARSE INPUT 
		self.urls = []
		for url in urls:
			self.urls.append(url.replace("'",""))

		self.name = name
		self.client_email = client_email
		self.session = False
		self.instance_filename = ""
		self.instance_responses = ()
		self.instance_results = ()
		self.new_results_titles = []
		self.new_results_links = []
		self.new_results = ()
		self.post_timing = []
		self.post_title_texts = []
		self.post_links = []
		self.num_posts = 0
		self.num_new_results = 0
		self.results_msg = ""
		self.EMAIL_ADDRESS = ""
		self.EMAIL_PASSWORD = ""

# USE IF/ELSE CONDITIONALS IN THIS FUNCTION TO DEFINE PERSONALIZED 
# SEARCH CRITERIA, REDUCE SPAM, SCRAPE, AND POPULATE RESULT LISTS.  

	def get_results(self):
		SPAM = "DoorDash"
		try:
			for url in self.urls:
				response = get(url)
				soup = BeautifulSoup(response.text,'html.parser')
				posts = soup.find_all('li',class_='result-row')
				
				for post in posts:
					post_title = post.find('a',class_='result-title hdrlnk')
					post_link = post_title['href']
					# SELECT A REGION AND CUT SPAM HERE TO REFINE RESULTS
					region = bool(post_link.split('/')[2].split('.')[0]=='westernmass')
					not_spam = bool(SPAM not in post_title.text)
					
					if region and not_spam :
						self.num_posts += 1

						post_title_text = post_title.text
						self.post_title_texts.append(post_title_text)

						self.post_links.append(post_link)

						post_datetime = post.find('time', class_= 'result-date')['title']
						self.post_timing.append(post_datetime)

		except Exception as e:
			print(f"\nThere was a problem scraping results!\n--> {e}")

		if self.num_posts:
			self.instance_results = (self.post_timing, self.post_title_texts, self.post_links, self.num_posts)
			return self.instance_results

		else:
			print(f"No new {self.name} search results")
			sys.exit()

# DATABASE CONNECTION 
	def db_connect(self):
		try:
			# BE CERTAIN THAT THE DB URI IS CORRECT
			engine = create_engine(f'sqlite:////home/jrob/Databases/{self.name}.db')  #echo=True for output to console
			Base.metadata.create_all(bind=engine)
			Session = sessionmaker(bind=engine)
			self.session = Session()

		except Exception as e:
			print(f"\nThere was a problem connecting to the database!\n--> {e}")

# CHECK FOR DUPLICATES (IntegrityError) AND UPDATE DB WITH UNIQUE RESULTS
	def db_update(self, instance_results, session):
		post_timing, post_title_texts, post_links, num_posts = instance_results

		duplicates = 0

		try:

			for i in range(len(post_links)):

				try:
					post = Posts()
					post.timing = post_timing[i]
					post.title_text = post_title_texts[i]
					self.new_results_titles.append(post_title_texts[i])
					post.link = post_links[i]
					self.new_results_links.append(post_links[i])
					self.session.add(post)
					self.session.commit()

				except exc.IntegrityError as e:
					duplicates += 1
					self.new_results_titles.pop()
					self.new_results_links.pop()
					self.session.rollback()
			
			self.new_results = (self.new_results_titles, self.new_results_links)
			self.num_new_results = num_posts - duplicates

			return self.num_new_results

		except Exception as e:
			print(f"\nThere was a problem updating the database!\n--> {e}")

	def db_close(self, session):
		self.session.close()

# FORMAT LOGGED OUTPUT RESULTS MESSAGE 
	def console_msg(self, new_results):
		titles, links = new_results

		if self.num_new_results:
			print(f"\n{self.num_new_results} New {self.name} Results\n")

			for result, index in enumerate(titles):
				print(f"Result {result + 1}\n\
					{titles[result]}\n\
					{links[result]}\n")
		else:
			print(f"\nNo new {self.name} search results\n")

# FORMAT USER EMAIL RESULTS MESSAGE
	def client_msg(self, new_results):
		titles, links = new_results

		for result, index in enumerate(titles):
			result = f"""
Result {result+1}
	{titles[result]}
	{links[result]}
			"""
			self.results_msg = self.results_msg + result

		return self.results_msg


# GET EMAIL CREDENTIALS
	def get_cred(self):
		try:
			self.EMAIL_ADDRESS = os.environ.get('EMAIL_USER')

			if not self.EMAIL_ADDRESS:
				print("\nThere was a problem obtaining environment variable for username and an email will not be sent!")
				sys.exit()

		except Exception as e:
			print(f"\nThere was a problem obtaining environment variable for your username!")

		try:
			self.EMAIL_PASSWORD = os.environ.get('EMAIL_PASS')

			if not self.EMAIL_PASSWORD:
				print("\nThere was a problem obtaining environment variable for your password and an email will not be sent!")
				sys.exit()

		except Exception as e:
			print(f"\nThere was a problem obtaining environment variable for your password!\n--> {e}")

		return self.EMAIL_ADDRESS, self.EMAIL_PASSWORD

# FORMAT AND SEND EMAIL
	def send_mail(self, EMAIL_ADDRESS, EMAIL_PASSWORD, results_msg):

		msg = EmailMessage()
		msg['Subject'] = f"{self.num_new_results} New {self.name} Search Results!"
		msg['From'] = self.EMAIL_ADDRESS
		msg['to'] = self.client_email, self.EMAIL_ADDRESS
		msg.set_content(self.results_msg)

		try:
			with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
			    smtp.login(self.EMAIL_ADDRESS, self.EMAIL_PASSWORD)
			    smtp.send_message(msg)
			print("Email Sent")

		except Exception as e:
			print(f"\nThere was a problem while attempting to send your email!\n--> {e}")

# USE AS MANY URLS AS POSSIBLE FROM THE MOST SPECIFIC POSSIBLE SEARCHES.
# SET QUERY PARAMATERS SUCH AS MIN/MAX PRICE, POSTED TODAY, SEARCH RADIUS, HAS PIC, ETC.


# PUT IT ALL TOGETHER IN A MAIN FUNCTION
def main():
	ds = DealScraper(args.urls, args.name, args.client_email)
	ds.get_results()
	ds.db_connect()
	ds.db_update(ds.instance_results, ds.session)
	ds.console_msg(ds.new_results)
	if ds.num_new_results:
		ds.db_close(ds.session)
		EMAIL_ADDRESS,EMAIL_PASSWORD = (ds.get_cred())
		ds.client_msg(ds.new_results)
		ds.send_mail(EMAIL_ADDRESS,EMAIL_PASSWORD, ds.results_msg)

	else:
		ds.db_close(ds.session)

	try:
		sys.exit()

	except SystemExit:
		pass 


if __name__ == '__main__':
	main()