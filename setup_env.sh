#!/bin/bash
echo "Setting up Jira Automation environment variables..."

read -p "Enter your Jira API Token: " JIRA_TOKEN

echo "export JIRA_DOMAIN='https://mufpm.atlassian.net'" >> ~/.bashrc
echo "export JIRA_EMAIL='okky.pratama@muf.co.id'" >> ~/.bashrc
echo "export JIRA_API_TOKEN='$JIRA_TOKEN'" >> ~/.bashrc

echo ""
echo "Environment variables added to ~/.bashrc"
echo "Run 'source ~/.bashrc' or restart your terminal."
