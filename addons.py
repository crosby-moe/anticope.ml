import requests
import json
from os import getenv
from time import sleep
import re

VERIFIED = json.load(open('verified.json', "r+", encoding='utf-8'))

RETRY_COUNT = 25

GH_TOKEN = getenv("GH_TOKEN")
HEADERS = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json", "User-Agent": "RacoonDog/anticope.ml"}

# regex
FEATURE_RE = re.compile("(?:add\(new )([^(]+)(?:\([^)]*)\)\)")
INVITE_RE = re.compile("((?:https?:\/\/)?(?:www.)?(?:discord.(?:gg|io|me|li|com)|discordapp.com\/invite|dsc.gg)\/[a-zA-z0-9-\/]+)")

def sleep_if_rate_limited(type="search"):
    for _ in range(RETRY_COUNT):
        try:
            r = requests.get("https://api.github.com/rate_limit", headers=HEADERS)
            if r.status_code != 304 and r.json()['resources'][type]['remaining'] > 0:
                return
            print("rate limited. sleeping...")
        except Exception:
            print("[rate limit] error. ignoring...")
        sleep(25)

def parse_repo(repoName):
    sleep_if_rate_limited(type="core")
    print(f"parsing: {repoName}")

    repoRes = requests.get(f"https://api.github.com/repos/{repoName}", headers=HEADERS)
    repo = repoRes.json()
    if repoRes.status_code == 404 or "block" in repo:
        raise Exception("Addon repository does not exist")

    fabricRes = requests.get(f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/src/main/resources/fabric.mod.json")
    if fabricRes.status_code == 404:
        # try client sourceset
        fabricRes = requests.get(f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/src/client/resources/fabric.mod.json")
        if fabricRes.status_code == 404:
            raise Exception("Addon repository has no fabric.mod.json!")
        
    fabric = fabricRes.json()

    # find authors from mod metadata or from github username
    authors = []
    if "authors" in fabric:
        for author in fabric['authors']:
            if type(author) == str:
                authors.append(author)
            else:
                authors.append(author["name"])
        if len(authors) == 0:
            authors.append(repo['owner']['login'])
    
    links = {"github": repo['html_url']}
    
    summary = None
    try:
        summary = fabric.get("description") or repo['description']
    except Exception:
        print("[summary] error. ignoring...")
    
    # direct download from releases
    downloads = 0
    try:
        releases = requests.get(f"https://api.github.com/repos/{repoName}/releases", headers=HEADERS).json()
        url = None
        for release in releases:
            for asset in release['assets']:
                asset_name: str = asset['name'].lower()
                if asset_name.endswith("-dev.jar") or asset_name.endswith("-sources.jar") or asset_name.endswith("-all.jar") or asset_name.endswith("-javadoc.jar"):
                    continue
                if asset_name.endswith(".jar"):
                    url = asset['browser_download_url']
                    downloads = asset['download_count']
                    break
            if url != None:
                break
        if url == None:
            print("missing release")
        else:
            links["download"] = url
    except Exception:
        print("[dl] error. ignoring...")
    
    # icon from mod metadata
    icon = None
    try:
        if "icon" in fabric:
            icon = f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/src/main/resources/{fabric['icon']}"
            if requests.head(icon).status_code == 404:
                icon = None
                
        # try default path
        if icon == None:
            icon = f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/src/main/resources/assets/{fabric['id']}/icon.png"
            if requests.head(icon).status_code == 404:
                print("missing icon")
                icon = None
    except Exception:
        print("[icon] error. ignoring...")
        icon = None

    # get discord server from fabric.mod.json
    if "contact" in fabric and "discord" in fabric["contact"]:
        links["discord"] = invite = fabric["contact"]["discord"]
    else:
        # find discord server by looking at readme mod and repository metadata
        try:
            readme = requests.get(f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/README.md").text
            invites = INVITE_RE.findall(readme) + INVITE_RE.findall(str(fabric)) + INVITE_RE.findall(str(repo))
            for invite in invites:
                if requests.head(invite).status_code != 404:
                    links["discord"] = invite
                    break
        except Exception:
            print("[discord invite] error. ignoring...")

    # get homepage from fabric.mod.json
    if "contact" in fabric and "homepage" in fabric["contact"]:
        links["homepage"] = fabric["contact"]["homepage"]
    else:
        try:
            site = repo['homepage']
            if not INVITE_RE.match(site) and site: # skip discord invites
                links["homepage"] = site
        except Exception:
            print(f"[homepage] error. ignoring...")

    # find features by parsing the entrypoint
    features = []
    if "entrypoints" in fabric and "meteor" in fabric["entrypoints"]:
        try:
            entrypoint = requests.get(f"https://raw.githubusercontent.com/{repoName}/{repo['default_branch']}/src/main/java/{fabric['entrypoints']['meteor'][0].replace('.', '/')}.java").text
            features.extend([str(x) for x in FEATURE_RE.findall(entrypoint)])
            if len(features) > 50:
                count = len(features) - 50
                features = features[:50]
                features.append(f"...and {count} more")
        except Exception:
            print("[features] error. ignoring...")
    
    result = {
        "authors": authors,
        "features": features,
        "icon": icon,
        "repo": repoName,
        "links": links,
        "name": fabric['name'] if "name" in fabric else repo["name"],
        "id": fabric['id'],
        "stars": repo['stargazers_count'],
        "last_update": repo['pushed_at'],
        "downloads": downloads,
        "status": {
            "archived": repo['archived']
        },
        "summary": summary
    }

    return result

data_json = []
for repo in VERIFIED:
    try:
        data_json.append(parse_repo(repo))
    except Exception as ex:
        print(f"error {ex}. ignored..., repo: {repo}")
            
json.dump(data_json, open("addons-data.json", "w+", encoding='utf-8'), indent=None)
