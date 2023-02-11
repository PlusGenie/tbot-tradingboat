import setuptools

import codecs
import os.path


def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), "r") as fp:
        return fp.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith("__version__"):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")


setuptools.setup(
    name="tbot_tradingboat",
    author="Sangwook Lee",
    author_email="aladdin@polusgenie.com",
    description="TV message decoder for IBKR",
    version=get_version("src/tbot_tradingboat/_version.py"),
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="."),
    python_requires=">=3.8",
    py_modules=['tbot_tradingboat'],
    entry_points={
        'console_scripts': [
            'tbot = tbot_tradingboat.main:main'
        ]
    }
)
