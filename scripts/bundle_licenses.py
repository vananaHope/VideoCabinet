"""Collect installed license texts for the actual Python bundle and npm production tree.

No network requests or additional npm dependencies are needed. Original files are
copied byte-for-byte; the manifests record their provenance and SHA-256.
"""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sys


LICENSE_SOURCES = Path(__file__).resolve().parents[1] / "installer/license-sources"
PYTHON_METADATA_ONLY = frozenset()  # Explicit exceptions only; none currently needed.
WEB_BUNDLED_BUILD_TOOLS = {"node_modules/tailwindcss", "node_modules/vite"}
PYTHON_SUPPLEMENTS = {
    ("ctranslate2", "4.8.3"): {
        "url": "https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.3/LICENSE",
        "sha256": "54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb",
    },
    ("tokenizers", "0.23.3"): {
        "url": "https://raw.githubusercontent.com/huggingface/tokenizers/v0.23.3/LICENSE",
        "sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    },
}


WEB_SUPPLEMENTS = {
    ('react-remove-scroll-bar', '2.3.8'): {
        'url': 'https://raw.githubusercontent.com/theKashey/react-remove-scroll-bar/'
               '7301c160fda44cb8cf2b9fdfde61efad35736196/LICENSE',
        'sha256': 'a79aae0c0f21990d9d963bb3c5a79cdcea9a46f8523ba55c58d7fe776b6ebc84',
    },
}


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def license_file(path):
    name = path.name.lower()
    return (name.startswith(('license', 'licence', 'copying', 'notice'))
            or 'thirdpartynotice' in name or 'third-party-notice' in name
            or ('licenses' in [p.lower() for p in path.parts[:-1]]
                and path.suffix.lower() not in ('.py', '.pyc', '.pyd')))


def copy_license(source, target, base):
    content = source.read_bytes()
    if not content.strip():
        raise RuntimeError(f'Empty license file: {source}')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {'path': target.relative_to(base).as_posix(),
            'sha256': hashlib.sha256(content).hexdigest()}


def python_licenses(entries, destination):
    """Match Analysis pure/binaries/datas source paths against wheel RECORD files.

    Matching files, rather than imports or requirements, handles shared namespaces
    (PySide6) and excludes installed-but-unbundled packages such as CUDA.
    PyInstaller itself contributes the executable bootloader in every build.
    """
    sources = {Path(entry[1]).resolve() for entry in entries if entry[1]}
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    packages = []
    seen = set()
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = re.sub(r'[-_.]+', '-', dist.metadata['Name']).lower()
        files = list(dist.files or ())
        if name in seen or name == 'my-video-manager':
            continue
        if name != 'pyinstaller' and not any(Path(dist.locate_file(f)).resolve() in sources for f in files):
            continue
        seen.add(name)
        info = dist.metadata
        license_name = info.get('License-Expression') or info.get('License')
        if not license_name:
            license_name = '; '.join(c.split(' :: ')[-1] for c in info.get_all('Classifier', [])
                                     if c.startswith('License ::'))
        urls = info.get_all('Project-URL', []) + info.get_all('Home-page', [])
        urls = [url for url in urls if 'https://' in url or 'http://' in url]
        originals = []
        for file in sorted(files):
            if not license_file(file):
                continue
            if file.is_absolute() or '..' in file.parts:
                raise RuntimeError(f'Unsafe license path: {name}: {file}')
            # Stable metadata directory, independent of the installed version.
            parts = list(file.parts)
            if parts[0].endswith(('.dist-info', '.egg-info')):
                parts[0] = 'metadata'
            target = destination / name / Path(*parts)
            record = copy_license(Path(dist.locate_file(file)), target, destination)
            originals.append({**record, 'source': str(file)})
        supplement = PYTHON_SUPPLEMENTS.get((name, dist.version))
        if not originals and supplement:
            source = LICENSE_SOURCES / f'{name}-{dist.version}' / 'LICENSE'
            if hashlib.sha256(source.read_bytes()).hexdigest() != supplement['sha256']:
                raise RuntimeError(f'Changed supplemental license: {source}')
            record = copy_license(source, destination / name / 'LICENSE', destination)
            originals.append({**record, 'source': supplement['url']})
        if not originals and (name, dist.version) not in PYTHON_METADATA_ONLY:
            raise RuntimeError(f'Missing license originals: {name} {dist.version}')
        if not originals and (not license_name or not urls):
            raise RuntimeError(f'Missing license name or URL for {name}')
        notice = (f'{info["Name"]} {dist.version}\nLicense: {license_name or "See original files"}\n'
                  + '\n'.join(urls) + '\n\n'
                  + ('Original license files are included below this directory.\n' if originals else
                     'This installed distribution contains no LICENSE, COPYING or NOTICE text.\n'
                     'License name and upstream URLs above are supplied from its package metadata.\n'))
        if name.startswith('pyside6') or name == 'shiboken6':
            notice += ('Distributed under LGPL-3.0; see licenses/LGPL-3.0.txt '
                       'and licenses/GPL-3.0.txt.\n')
        write_text(destination / name / 'NOTICE.txt', notice)
        packages.append({'name': name, 'version': dist.version, 'license': license_name,
                         'urls': urls, 'files': originals, 'metadata_only': not originals})
    if not packages:
        raise RuntimeError('No bundled Python distributions found')
    source = Path(sys.base_prefix, 'LICENSE.txt')
    record = copy_license(source, destination / 'python/LICENSE.txt', destination)
    packages.append({'name': 'python', 'version': sys.version, 'license': 'PSF-2.0',
                     'files': [{**record, 'source': str(source)}], 'metadata_only': False})
    write_text(destination / 'manifest.json', json.dumps(packages, indent=2, ensure_ascii=False) + '\n')
    return packages


def web_licenses(frontend, destination):
    """Use npm lockfile v3 dev flags, including transitive and peer dependencies."""
    lock = json.loads((frontend / 'package-lock.json').read_text(encoding='utf-8'))
    if lock.get('lockfileVersion') != 3:
        raise RuntimeError('Expected npm lockfileVersion 3')
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    packages, sections = [], []
    for location, locked in sorted(lock['packages'].items()):
        # devOptional can also be an optional dependency of production code.
        if not location or (locked.get('dev') and location not in WEB_BUNDLED_BUILD_TOOLS):
            continue
        relative = Path(location)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'node_modules':
            raise RuntimeError(f'Unsafe npm package path: {location}')
        directory = frontend / relative
        package = json.loads((directory / 'package.json').read_text(encoding='utf-8'))
        if package['version'] != locked['version']:
            raise RuntimeError(f'npm package version differs from lockfile: {location}')
        originals = []
        # Do not recurse into a nested dependency's node_modules: each package has its own entry.
        for path in sorted(directory.rglob('*')):
            local = path.relative_to(directory)
            if 'node_modules' in local.parts or not path.is_file() or not license_file(local):
                continue
            record = copy_license(path, destination / relative / local, destination)
            originals.append(record)
        supplement = WEB_SUPPLEMENTS.get((package['name'], package['version']))
        if not originals and supplement:
            source = (frontend.parent / 'installer/license-sources'
                      / f'{package["name"]}-{package["version"]}' / 'LICENSE')
            if hashlib.sha256(source.read_bytes()).hexdigest() != supplement['sha256']:
                raise RuntimeError(f'Changed supplemental license: {source}')
            record = copy_license(source, destination / relative / 'LICENSE', destination)
            originals.append({**record, 'source': supplement['url']})
        if not originals:
            raise RuntimeError(f'No original license text in npm production package: {location}')
        sections.append(f'{package["name"]} {package["version"]}\n'
                        f'License: {package.get("license", locked.get("license", "See original files"))}\n'
                        f'Source: {locked.get("resolved", "")}\n'
                        + ''.join(f'Original: {f["path"]}\n'
                                  + (f'License source: {f["source"]}\n' if 'source' in f else '')
                                  for f in originals))
        packages.append({'name': package['name'], 'version': package['version'],
                         'location': location, 'files': originals})
    if not packages:
        raise RuntimeError('No npm production licenses found')
    write_text(destination / 'THIRD-PARTY-WEB.txt',
               'npm production dependencies (including transitive dependencies)\n\n' + '\n'.join(sections))
    write_text(destination / 'manifest.json', json.dumps(packages, indent=2) + '\n')
    return packages


def collect_bundle_licenses(analysis, root, stage):
    destination = stage / 'licenses'
    python_licenses([*analysis.pure, *analysis.binaries, *analysis.datas], destination / 'python')
    web_licenses(root / 'frontend', destination / 'web')
    return [(str(Path('licenses') / path.relative_to(destination)), str(path), 'DATA')
            for path in sorted(destination.rglob('*')) if path.is_file()]
