@echo off
echo Setting up Jira Automation environment variables...

set /p JIRA_TOKEN="Enter your Jira API Token: "

setx JIRA_DOMAIN "https://mufpm.atlassian.net"
setx JIRA_EMAIL "okky.pratama@muf.co.id"
setx JIRA_API_TOKEN "%JIRA_TOKEN%"

echo.
echo Environment variables set successfully!
echo Please restart your terminal for changes to take effect.
pause
