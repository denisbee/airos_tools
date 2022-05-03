from setuptools import setup, find_packages

with open("README.md", "r") as fh:
      long_description = fh.read()

setup(
      name='airos_tools',
      version='0.2',
      description='Ubiquti AirOS SSH helper',
      author='Denis Bezrodnykh',
      author_email='denis.bee@gmail.com',
      url='https://github.com/denisbee/airos_tools',
      python_requires='>=3.5',
      packages=find_packages(),
      long_description=long_description,
      long_description_content_type="text/markdown",
      install_requires=[ 'paramiko~>2.10.1', 'cached_property~=1.5' ]
)
