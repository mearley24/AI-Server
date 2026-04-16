mkdir -p /Users/bob/AI-Server/data/x_posts
cp /Users/bob/AI-Server/scripts/launchd/com.symphony.x-autoposter.plist /Users/bob/Library/LaunchAgents/com.symphony.x-autoposter.plist
launchctl load /Users/bob/Library/LaunchAgents/com.symphony.x-autoposter.plist
echo "X autoposter launchd service installed and loaded."
echo "Runs at: 8am, 10am, 12pm, 2pm, 4pm, 6pm, 8pm Mountain Time."
echo "Logs: /Users/bob/AI-Server/data/x_posts/scheduler.log"
echo "To unload: launchctl unload /Users/bob/Library/LaunchAgents/com.symphony.x-autoposter.plist"
