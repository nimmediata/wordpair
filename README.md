# wordpair
Find a word that obeys the same constraints in both languages.

## Build freedict English↔Italian pairs
```sh
python wordpair.py build
```

## Example
```sh
python wordpair.py ask --en-start C --en-len 6 --it-start C --it-len 5
python wordpair.py solve --en-start C --en-len 6 --it-start C --it-len 5 --limit 10
python wordpair.py check coffee caffè
```

