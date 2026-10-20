-- KOReader News Downloader entry for the morning brief.
-- Easiest: add it in KOReader (News downloader → Settings → feeds), using these values.
-- Or paste this line into the feed list in KOReader's news downloader config file.
-- Points at the thirstyrhino/kindle-hub site.
{ "https://thirstyrhino.github.io/kindle-hub/brief.xml", limit = 1, download_full_article = false, include_images = false },
-- limit = 1                     -> only today's brief
-- download_full_article = false -> build the ebook from the feed itself (the whole brief is in it)
