# Test script to check if everything works
print("Hello! Starting GitHub data collection setup...")
print("If you see this message, Python is working!")

# Test PyGithub import
try:
    from github import Github
    print("✓ PyGithub is installed correctly!")
except ImportError:
    print("✗ PyGithub is NOT installed. Run: pip install PyGithub")

# Test pandas import
try:
    import pandas as pd
    print("✓ Pandas is installed correctly!")
except ImportError:
    print("✗ Pandas is NOT installed. Run: pip install pandas")

print("\nSetup test complete!")