"""Debug script to test Flask routes"""
import sys
import os

# Add the current directory to path
sys.path.insert(0, os.getcwd())

# Try to import and check routes
try:
    from app import app
    print("✅ App imported successfully")
    print("\n📋 Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.rule} -> {rule.endpoint} [{', '.join(rule.methods - {'HEAD', 'OPTIONS'})}]")
except Exception as e:
    print(f"❌ Error importing app: {e}")
    import traceback
    traceback.print_exc()