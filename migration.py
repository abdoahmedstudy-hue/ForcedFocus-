import os
import shutil
import subprocess

REPO_DIR = "/Volumes/ssd/File/App/ForcedFocus/ForcedFocus "
OLD_V_DIR = "/Volumes/ssd/File/App/ForcedFocus/old V"

os.chdir(REPO_DIR)

print("Starting migration...")

try:
    # Ensure clean state on main
    subprocess.run(["git", "checkout", "main", "--force"], check=True)
    subprocess.run(["git", "checkout", "--orphan", "archive/legacy-versions"], check=True)
    subprocess.run(["git", "rm", "-rf", "."], check=False)

    branches_to_push = []

    for i in range(1, 17):
        print(f"Processing V{i}...")
        src_dir = os.path.join(OLD_V_DIR, f"ForcedFocus V{i}" if i < 16 else f"V{i}")
        
        # Clean current directory except .git and migration.py
        for item in os.listdir(REPO_DIR):
            if item not in [".git", "migration.py"]:
                path = os.path.join(REPO_DIR, item)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                    
        # Copy from src_dir
        for item in os.listdir(src_dir):
            s = os.path.join(src_dir, item)
            d = os.path.join(REPO_DIR, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
                
        # Commit
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", f"Archive physical copy: V{i}"], check=False)
        
        # Branch
        branch_name = f"archive/V{i}"
        subprocess.run(["git", "branch", branch_name], check=True)
        branches_to_push.append(branch_name)

    print("Checking out main and cleaning...")
    subprocess.run(["git", "checkout", "main", "--force"], check=True)
    subprocess.run(["git", "clean", "-fd"], check=True)

    print("Pushing branches...")
    push_cmd = ["git", "push", "origin"] + branches_to_push
    subprocess.run(push_cmd, check=True)

    print("Migration completed.")
except Exception as e:
    print(f"Error occurred: {e}")
