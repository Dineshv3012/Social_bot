import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import google.oauth2.credentials
from instagrapi import Client
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.page import Page
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import ffmpeg

# Initialize environment
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('social_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SocialMediaBot')

class SocialMediaBot:
    def __init__(self):
        self.cred_manager = self.CredentialManager()
        self.accounts = self._load_accounts()
        self.settings = self._load_settings()
        self.clients = self._initialize_clients()
        self._setup_directories()

    class CredentialManager:
        def __init__(self):
            key = os.getenv('ENCRYPTION_KEY')
            if not key:
                key = Fernet.generate_key().decode()
                logger.warning(f"No encryption key found. Generated new key: {key}")
            self.cipher = Fernet(key.encode())

        def encrypt(self, data: str) -> str:
            return self.cipher.encrypt(data.encode()).decode()

        def decrypt(self, encrypted_data: str) -> str:
            return self.cipher.decrypt(encrypted_data.encode()).decode()

    def _load_accounts(self) -> Dict:
        accounts_file = Path('config/accounts.json')
        if accounts_file.exists():
            with open(accounts_file, 'r') as f:
                return json.load(f)
        return {}

    def _load_settings(self) -> Dict:
        settings_file = Path('config/settings.json')
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                return json.load(f)
        return {'platforms': {}, 'default_platforms': []}

    def _setup_directories(self):
        Path('uploads').mkdir(exist_ok=True)
        Path('uploads/processed').mkdir(exist_ok=True)
        Path('config').mkdir(exist_ok=True)
        Path('logs').mkdir(exist_ok=True)

    def _initialize_clients(self) -> Dict:
        clients = {}
        
        # YouTube Client
        if 'youtube' in self.accounts:
            try:
                creds = None
                token_path = Path('config/youtube_token.json')
                
                if token_path.exists():
                    creds = google.oauth2.credentials.Credentials.from_authorized_user_file(token_path)
                
                if not creds or not creds.valid:
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                    else:
                        flow = InstalledAppFlow.from_client_secrets_file(
                            'config/youtube_credentials.json',
                            scopes=['https://www.googleapis.com/auth/youtube.upload']
                        )
                        creds = flow.run_local_server(port=0)
                    
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                
                clients['youtube'] = build('youtube', 'v3', credentials=creds)
                logger.info("YouTube client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize YouTube client: {str(e)}")

        # Instagram Client
        if 'instagram' in self.accounts:
            try:
                cl = Client()
                cl.login(
                    self.accounts['instagram']['username'],
                    self.cred_manager.decrypt(self.accounts['instagram']['password'])
                )
                clients['instagram'] = cl
                logger.info("Instagram client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Instagram client: {str(e)}")

        # Facebook Client
        if 'facebook' in self.accounts:
            try:
                FacebookAdsApi.init(
                    self.accounts['facebook']['app_id'],
                    self.accounts['facebook']['app_secret'],
                    self.cred_manager.decrypt(self.accounts['facebook']['access_token'])
                )
                clients['facebook'] = Page(self.accounts['facebook']['page_id'])
                logger.info("Facebook client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Facebook client: {str(e)}")

        return clients

    def _process_video(self, video_path: str, platform: str) -> str:
        """Convert video to platform-optimal format"""
        output_path = f"uploads/processed/{platform}_{Path(video_path).name}"
        
        try:
            if platform == 'instagram':
                (
                    ffmpeg.input(video_path)
                    .filter('scale', 1080, 1350)
                    .output(output_path, vcodec='libx264', preset='fast', crf=22)
                    .run(overwrite_output=True)
            elif platform == 'youtube':
                (
                    ffmpeg.input(video_path)
                    .output(output_path, vcodec='libx264', preset='medium', crf=18)
                    .run(overwrite_output=True)
            else:  # Facebook
                (
                    ffmpeg.input(video_path)
                    .output(output_path, vcodec='libx264', preset='fast', crf=20)
                    .run(overwrite_output=True)
            
            return output_path
        except Exception as e:
            logger.error(f"Video processing failed: {str(e)}")
            return video_path  # Fallback to original

    def upload_to_youtube(self, video_path: str, options: Dict) -> bool:
        try:
            processed_path = self._process_video(video_path, 'youtube')
            upload_type = options.get('type', 'video')
            
            metadata = {
                'snippet': {
                    'title': options.get('title', 'My Video'),
                    'description': options.get('description', ''),
                    'tags': options.get('tags', []),
                    'categoryId': options.get('category', '22')
                },
                'status': {
                    'privacyStatus': options.get('privacy', 'public')
                }
            }

            if upload_type == 'short':
                metadata['snippet']['short'] = True

            request = self.clients['youtube'].videos().insert(
                part=",".join(metadata.keys()),
                body=metadata,
                media_body=processed_path
            )
            response = request.execute()
            logger.info(f"YouTube upload successful: {response['id']}")
            return True
        except Exception as e:
            logger.error(f"YouTube upload failed: {str(e)}")
            return False

    def upload_to_instagram(self, video_path: str, options: Dict) -> bool:
        try:
            processed_path = self._process_video(video_path, 'instagram')
            upload_type = options.get('type', 'feed')
            
            if upload_type == 'reels':
                self.clients['instagram'].clip_upload(
                    processed_path,
                    caption=options.get('caption', '')
                )
            elif upload_type == 'story':
                self.clients['instagram'].video_upload_to_story(processed_path)
            else:  # regular feed
                self.clients['instagram'].video_upload(
                    processed_path,
                    caption=options.get('caption', '')
                )
            
            logger.info("Instagram upload successful")
            return True
        except Exception as e:
            logger.error(f"Instagram upload failed: {str(e)}")
            return False

    def upload_to_facebook(self, video_path: str, options: Dict) -> bool:
        try:
            processed_path = self._process_video(video_path, 'facebook')
            upload_type = options.get('type', 'feed')
            
            if upload_type == 'reels':
                self.clients['facebook'].create_reel(
                    video_file=processed_path,
                    description=options.get('message', '')
                )
            else:  # regular video
                self.clients['facebook'].create_video(
                    video_file=processed_path,
                    description=options.get('message', '')
                )
            
            logger.info("Facebook upload successful")
            return True
        except Exception as e:
            logger.error(f"Facebook upload failed: {str(e)}")
            return False

    def distribute_video(self, video_path: str, platforms: Optional[List[str]] = None) -> Dict:
        if not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return {}

        if platforms is None:
            platforms = self.settings.get('default_platforms', [])

        results = {}
        for platform in platforms:
            if platform not in self.clients:
                logger.warning(f"No client available for platform: {platform}")
                continue

            try:
                if platform == 'youtube':
                    results[platform] = self.upload_to_youtube(
                        video_path,
                        self.settings['platforms'].get('youtube', {})
                    )
                elif platform == 'instagram':
                    results[platform] = self.upload_to_instagram(
                        video_path,
                        self.settings['platforms'].get('instagram', {})
                    )
                elif platform == 'facebook':
                    results[platform] = self.upload_to_facebook(
                        video_path,
                        self.settings['platforms'].get('facebook', {})
                    )
                
                time.sleep(5)  # Rate limiting
            except Exception as e:
                logger.error(f"Error during {platform} upload: {str(e)}")
                results[platform] = False

        return results

    def process_upload_folder(self):
        upload_dir = Path('uploads')
        for video_file in upload_dir.glob('*.*'):
            if video_file.suffix.lower() in ['.mp4', '.mov', '.avi', '.mkv']:
                logger.info(f"Processing {video_file.name}")
                results = self.distribute_video(str(video_file))
                
                # Move to processed
                processed_path = upload_dir / 'processed' / video_file.name
                video_file.rename(processed_path)
                logger.info(f"Moved to processed: {video_file.name}")

    def interactive_menu(self):
        while True:
            print("\nSocial Media Bot Menu:")
            print("1. Upload a video")
            print("2. Process upload folder")
            print("3. Check account status")
            print("4. Exit")
            
            choice = input("Select an option: ")
            
            if choice == '1':
                video_path = input("Enter video file path: ")
                if not Path(video_path).exists():
                    print("File not found!")
                    continue
                
                print("Available platforms:", list(self.clients.keys()))
                platforms = input("Enter platforms (comma separated, leave blank for default): ")
                platforms = [p.strip() for p in platforms.split(',')] if platforms else None
                
                results = self.distribute_video(video_path, platforms)
                print("Upload results:", results)
            
            elif choice == '2':
                self.process_upload_folder()
                print("Upload folder processed")
            
            elif choice == '3':
                print("\nActive Platforms:")
                for platform, client in self.clients.items():
                    print(f"- {platform}: {'Connected' if client else 'Not connected'}")
            
            elif choice == '4':
                break
            
            else:
                print("Invalid option")

if __name__ == "__main__":
    bot = SocialMediaBot()
    if bot.clients:
        bot.process_upload_folder()  # Automatically processes uploads