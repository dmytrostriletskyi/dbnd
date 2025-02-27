import os
import re


def clean_links(path_to_file):
    if path_to_file[-5:] == ".html":
        with open(f"_build/html/reference/{path_to_file}", "r") as file:
            html = file.read()
            group_lower = lambda x: f'href="{x.group(1).lower()}"{x.group(2)}'
            html = re.sub(
                r"href=\"(?:api\/)?(?:dbnd\.)?(\w+)\.html(?:#dbnd\.\w+)?\"(>)?",
                group_lower,
                html,
                0,
                re.MULTILINE,
            )
        with open(f"_build/html/reference/{path_to_file}", "w") as file:
            file.write(html)


if __name__ == "__main__":
    os.system("sphinx-build -M clean . _build")
    os.system("sphinx-build -M html . _build")
    for name in os.listdir("_build/html/reference"):
        clean_links(name)
    for name in os.listdir("_build/html/reference/api"):
        clean_links(f"api/{name}")
    print("\n\n\033[92mBuild is finished! See the results at docs/_build/html!\033[0m")
