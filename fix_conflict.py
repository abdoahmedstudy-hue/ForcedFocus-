import re

with open('tests/test_forcefocus_cli.py', 'r') as f:
    content = f.read()

# Replace the conflict markers and keep both test classes
fixed_content = re.sub(r'<<<<<<< HEAD\n(.*?)\n=======\n(.*?)>>>>>>> bd76397[^\n]*\n', r'\1\n\n\2\n', content, flags=re.DOTALL)

with open('tests/test_forcefocus_cli.py', 'w') as f:
    f.write(fixed_content)
