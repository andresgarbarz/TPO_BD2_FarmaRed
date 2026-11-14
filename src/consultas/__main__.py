"""Lista las quince consultas. No las ejecuta."""

from . import CONSULTAS


def main() -> None:
    for consulta in CONSULTAS:
        print(f"{consulta.ID}  {consulta.TIPO:<12}  {consulta.DESCRIPCION}")


if __name__ == "__main__":
    main()
