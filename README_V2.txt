US MARKET AUTO NEWS V2

Replace:
- main.py
- .github/workflows/market.yml
- requirements.txt

Keep:
- templates/master.png
- data/

The V2 renderer:
- uses the static master image
- creates 7 redesigned information slides
- uses short mobile-friendly copy
- adds metric cards only from real supplied numbers
- adds ticker cards
- adds subtle Ken-Burns motion to every slide
- creates one vertical MP4
- uploads to YouTube

Schedule is unchanged:
8:30 AM ET
10:00 AM ET
1:00 PM ET
4:15 PM ET

First V2 run stays PRIVATE.
After visual approval, change:
YOUTUBE_PRIVACY_STATUS: private
to:
YOUTUBE_PRIVACY_STATUS: public

Do not add Cloudinary or Pollinations.
