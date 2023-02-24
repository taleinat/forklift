forklift
========
Make Python CLI tools blazing fast 🚀


# Why?

Entirely avoid the relatively long time taken for Python interpreter startup +
imports.

This is significant, for example, when running code linting and formatting
tools on just a few files in SCM hooks, such as via
[pre-commit](https://pre-commit.com/).


# Installation

Install into the same Python env where you have tools like black or flake8
installed:

```shell
pip install git+https://github.com/taleinat/forklift.git
```


# Usage

Example:

```shell
forklift start black
time forklift run black --help
time black --check .
time forklift run black --check .
forklift stop black
```

# Copyright & License

Copyright 2022-2023 Tal Einat.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.


Version 3.90 of the filelock library is included in this codebase as-is. It is
made available under the terms of the Unlicense software license. See it's
LICENSE file for details.
